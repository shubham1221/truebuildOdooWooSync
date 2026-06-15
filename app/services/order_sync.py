"""
TrueBuild Integration Platform — Order Sync Service.

Orchestrates order synchronization from WooCommerce to Odoo.
Each WooCommerce order creates a Sales Order in Odoo with:
- Customer matching/creation
- Order lines with product SKU validation
- GST tax application
- Sales Order confirmation
- Invoice creation attempt

Idempotent: duplicate orders are detected and skipped.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.database.models import OrderStatus
from app.repositories.order_repo import OrderMappingRepository
from app.repositories.product_repo import ProductMappingRepository
from app.repositories.variant_repo import VariantMappingRepository
from app.repositories.sync_log_repo import SyncLogRepository
from app.repositories.failed_job_repo import FailedJobRepository
from app.schemas.customer import CustomerData
from app.schemas.order import OrderLineItem, OrderSyncData, OrderSyncResult
from app.services.odoo_client import OdooClient, OdooAPIError
from app.services.woo_client import WooCommerceClient, WooCommerceAPIError
from app.services.customer_sync import CustomerSyncService
from app.utils.logging import get_logger

logger = get_logger(__name__)


class OrderSyncService:
    """
    Orchestrates WooCommerce → Odoo order synchronization.

    Flow:
    1. Receive WooCommerce order (webhook or manual)
    2. Check OrderMapping for idempotency
    3. Extract customer → CustomerSyncService
    4. Validate all line item SKUs
    5. Create sale.order with order lines
    6. Confirm sale order
    7. Create invoice (attempt)
    8. Post invoice (attempt)
    9. Update mappings
    """

    def __init__(
        self,
        odoo: OdooClient,
        woo: WooCommerceClient,
        db: Session,
    ) -> None:
        self.odoo = odoo
        self.woo = woo
        self.db = db
        self.settings = get_settings()
        self.order_repo = OrderMappingRepository(db)
        self.product_repo = ProductMappingRepository(db)
        self.variant_repo = VariantMappingRepository(db)
        self.sync_log_repo = SyncLogRepository(db)
        self.failed_job_repo = FailedJobRepository(db)
        self.customer_sync = CustomerSyncService(odoo, db)

    def sync_order(self, woo_order_id: int) -> OrderSyncResult:
        """
        Sync a single WooCommerce order to Odoo.

        Fetches the full order from WooCommerce and processes it.

        Args:
            woo_order_id: WooCommerce order ID.

        Returns:
            OrderSyncResult with action and status.
        """
        logger.info("order_sync_started", woo_order_id=woo_order_id)

        # Check idempotency
        existing = self.order_repo.get_by_woo_id(woo_order_id)
        if existing and existing.status == OrderStatus.SYNCED:
            logger.info(
                "order_already_synced",
                woo_order_id=woo_order_id,
                odoo_order_id=existing.odoo_order_id,
            )
            return OrderSyncResult(
                woo_order_id=woo_order_id,
                odoo_order_id=existing.odoo_order_id,
                action="skipped",
                message="Order already synced",
            )

        try:
            # Fetch complete order from WooCommerce
            woo_order = self.woo.get_order(woo_order_id)
            order_data = self._parse_woo_order(woo_order)
            return self._process_order(order_data, existing)

        except (OdooAPIError, WooCommerceAPIError) as e:
            return self._handle_order_error(woo_order_id, existing, e)
        except Exception as e:
            return self._handle_order_error(woo_order_id, existing, e)

    def sync_order_from_payload(self, payload: dict[str, Any]) -> OrderSyncResult:
        """
        Sync an order directly from a webhook payload.

        Used when the webhook already contains the full order data.

        Args:
            payload: WooCommerce webhook payload (full order JSON).

        Returns:
            OrderSyncResult.
        """
        woo_order_id = payload.get("id")
        if not woo_order_id:
            return OrderSyncResult(
                woo_order_id=0,
                action="failed",
                message="Invalid webhook payload: missing order ID",
            )

        # Check idempotency
        existing = self.order_repo.get_by_woo_id(woo_order_id)
        if existing and existing.status == OrderStatus.SYNCED:
            logger.info("order_already_synced", woo_order_id=woo_order_id)
            return OrderSyncResult(
                woo_order_id=woo_order_id,
                odoo_order_id=existing.odoo_order_id,
                action="skipped",
                message="Order already synced",
            )

        try:
            order_data = self._parse_woo_order(payload)
            return self._process_order(order_data, existing)
        except Exception as e:
            return self._handle_order_error(woo_order_id, existing, e)

    # ── Internal Processing ──────────────────────────────────────────────

    def _process_order(
        self,
        order_data: OrderSyncData,
        existing_mapping: Any | None,
    ) -> OrderSyncResult:
        """Process a parsed WooCommerce order into Odoo."""
        start_time = time.monotonic()
        woo_order_id = order_data.woo_order_id

        try:
            # ── 1. Create/match customer ─────────────────────────────
            customer_data = CustomerData(
                email=order_data.billing_email,
                first_name=order_data.billing_first_name,
                last_name=order_data.billing_last_name,
                phone=order_data.billing_phone,
                company=order_data.billing_company,
                address_1=order_data.billing_address_1,
                address_2=order_data.billing_address_2,
                city=order_data.billing_city,
                state=order_data.billing_state,
                postcode=order_data.billing_postcode,
                country=order_data.billing_country,
            )
            odoo_partner_id = self.customer_sync.get_or_create_partner(customer_data)

            # ── 2. Build order lines ─────────────────────────────────
            order_lines = self._build_order_lines(order_data.line_items)

            if not order_lines:
                raise ValueError(
                    f"No valid order lines for WooCommerce order {woo_order_id}. "
                    "All SKUs may be missing or unmapped."
                )

            # ── 3. Create Sale Order in Odoo ─────────────────────────
            so_values: dict[str, Any] = {
                "partner_id": odoo_partner_id,
                "client_order_ref": f"WC-{order_data.order_number or woo_order_id}",
                "note": order_data.customer_note or "",
                "order_line": order_lines,
            }

            odoo_order_id = self.odoo.create_sale_order(so_values)
            logger.info(
                "odoo_sale_order_created",
                woo_order_id=woo_order_id,
                odoo_order_id=odoo_order_id,
            )

            # ── 4. Confirm Sale Order ────────────────────────────────
            self.odoo.confirm_sale_order(odoo_order_id)
            logger.info("odoo_sale_order_confirmed", odoo_order_id=odoo_order_id)

            # ── 5. Create Invoice (attempt) ──────────────────────────
            odoo_invoice_id = None
            invoice_result = self.odoo.create_invoice_from_order(odoo_order_id)
            if invoice_result:
                # invoice_result is usually a list of invoice IDs
                if isinstance(invoice_result, list) and invoice_result:
                    odoo_invoice_id = invoice_result[0]
                elif isinstance(invoice_result, int):
                    odoo_invoice_id = invoice_result

                # ── 6. Post Invoice ──────────────────────────────────
                if odoo_invoice_id:
                    self.odoo.post_invoice(odoo_invoice_id)
                    logger.info(
                        "odoo_invoice_posted",
                        odoo_order_id=odoo_order_id,
                        odoo_invoice_id=odoo_invoice_id,
                    )

            # ── 7. Update Mapping ────────────────────────────────────
            if existing_mapping:
                self.order_repo.mark_synced(
                    existing_mapping,
                    odoo_order_id=odoo_order_id,
                    odoo_invoice_id=odoo_invoice_id,
                )
            else:
                self.order_repo.create(
                    woo_order_id=woo_order_id,
                    order_number=order_data.order_number,
                    odoo_order_id=odoo_order_id,
                    odoo_invoice_id=odoo_invoice_id,
                    total_amount=order_data.total,
                    currency=order_data.currency,
                    status=OrderStatus.SYNCED,
                )

            # ── 8. Audit Log ─────────────────────────────────────────
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self.sync_log_repo.log_success(
                event_type="order_created",
                entity_type="order",
                entity_id=str(woo_order_id),
                direction="woo_to_odoo",
                message=(
                    f"WC Order {woo_order_id} → Odoo SO {odoo_order_id}"
                    + (f" → Invoice {odoo_invoice_id}" if odoo_invoice_id else "")
                ),
                duration_ms=duration_ms,
            )

            self.db.commit()

            return OrderSyncResult(
                woo_order_id=woo_order_id,
                odoo_order_id=odoo_order_id,
                odoo_invoice_id=odoo_invoice_id,
                action="created",
                message=f"Sales Order {odoo_order_id} created in Odoo",
            )

        except Exception as e:
            self.db.rollback()
            raise

    def _build_order_lines(
        self,
        line_items: list[OrderLineItem],
    ) -> list[tuple[int, int, dict[str, Any]]]:
        """
        Build Odoo sale.order.line tuples from WooCommerce line items.

        Each line item's SKU is looked up in ProductMapping/VariantMapping
        to find the corresponding Odoo product.product ID.

        Returns:
            List of (0, 0, {values}) tuples for Odoo create.
        """
        order_lines = []

        for item in line_items:
            sku = item.sku
            if not sku:
                logger.warning(
                    "order_line_no_sku",
                    woo_line_id=item.woo_line_id,
                    product_name=item.name,
                )
                continue

            # Find Odoo product ID by SKU
            odoo_product_id = self._find_odoo_product_id(sku)
            if not odoo_product_id:
                logger.error(
                    "order_line_sku_not_mapped",
                    sku=sku,
                    product_name=item.name,
                )
                raise ValueError(
                    f"SKU '{sku}' not found in product mappings. "
                    "Ensure the product is synced before processing orders."
                )

            # Build order line values
            line_values = {
                "product_id": odoo_product_id,
                "product_uom_qty": item.quantity,
                "price_unit": float(item.price),
                "name": item.name or sku,
            }

            order_lines.append((0, 0, line_values))

        return order_lines

    def _find_odoo_product_id(self, sku: str) -> int | None:
        """
        Find the Odoo product.product ID for a given SKU.

        Checks VariantMapping first (for variants), then ProductMapping
        (for simple products — falls back to finding the single variant).
        """
        # Check variant mapping first
        variant_mapping = self.variant_repo.get_by_sku(sku)
        if variant_mapping:
            return variant_mapping.odoo_variant_id

        # Check product mapping (simple products)
        product_mapping = self.product_repo.get_by_sku(sku)
        if product_mapping:
            # For sale.order.line, we need product.product ID, not product.template ID
            # Simple products have one variant with the same SKU
            variants = self.odoo.search_read(
                "product.product",
                [["product_tmpl_id", "=", product_mapping.odoo_product_id]],
                fields=["id"],
                limit=1,
            )
            if variants:
                return variants[0]["id"]
            return None

        return None

    def _parse_woo_order(self, woo_order: dict[str, Any]) -> OrderSyncData:
        """Parse a WooCommerce order JSON into OrderSyncData."""
        billing = woo_order.get("billing", {})
        shipping = woo_order.get("shipping", {})

        line_items = []
        for item in woo_order.get("line_items", []):
            line_items.append(OrderLineItem(
                woo_line_id=item.get("id", 0),
                product_id=item.get("product_id", 0),
                variation_id=item.get("variation_id", 0),
                sku=item.get("sku", ""),
                name=item.get("name", ""),
                quantity=item.get("quantity", 1),
                price=str(item.get("price", "0.00")),
                subtotal=str(item.get("subtotal", "0.00")),
                total=str(item.get("total", "0.00")),
                total_tax=str(item.get("total_tax", "0.00")),
            ))

        return OrderSyncData(
            woo_order_id=woo_order.get("id", 0),
            order_number=str(woo_order.get("number", "")),
            status=woo_order.get("status", ""),
            currency=woo_order.get("currency", "AUD"),
            total=str(woo_order.get("total", "0.00")),
            total_tax=str(woo_order.get("total_tax", "0.00")),
            shipping_total=str(woo_order.get("shipping_total", "0.00")),
            discount_total=str(woo_order.get("discount_total", "0.00")),
            payment_method=woo_order.get("payment_method", ""),
            payment_method_title=woo_order.get("payment_method_title", ""),
            customer_note=woo_order.get("customer_note", ""),
            date_created=woo_order.get("date_created", ""),
            line_items=line_items,
            billing_email=billing.get("email", ""),
            billing_first_name=billing.get("first_name", ""),
            billing_last_name=billing.get("last_name", ""),
            billing_phone=billing.get("phone", ""),
            billing_company=billing.get("company", ""),
            billing_address_1=billing.get("address_1", ""),
            billing_address_2=billing.get("address_2", ""),
            billing_city=billing.get("city", ""),
            billing_state=billing.get("state", ""),
            billing_postcode=billing.get("postcode", ""),
            billing_country=billing.get("country", "AU"),
            shipping_first_name=shipping.get("first_name", ""),
            shipping_last_name=shipping.get("last_name", ""),
            shipping_address_1=shipping.get("address_1", ""),
            shipping_address_2=shipping.get("address_2", ""),
            shipping_city=shipping.get("city", ""),
            shipping_state=shipping.get("state", ""),
            shipping_postcode=shipping.get("postcode", ""),
            shipping_country=shipping.get("country", "AU"),
        )

    def _handle_order_error(
        self,
        woo_order_id: int,
        existing_mapping: Any | None,
        error: Exception,
    ) -> OrderSyncResult:
        """Handle order sync errors with retry queue."""
        logger.error(
            "order_sync_failed",
            woo_order_id=woo_order_id,
            error=str(error),
            exc_info=True,
        )

        self.sync_log_repo.log_failure(
            event_type="order_sync",
            entity_type="order",
            entity_id=str(woo_order_id),
            direction="woo_to_odoo",
            message=str(error),
        )

        # Create failed job for retry
        self.failed_job_repo.create(
            job_type="order_sync",
            entity_type="order",
            entity_id=str(woo_order_id),
            payload={"woo_order_id": woo_order_id},
            error_message=str(error),
            max_retries=self.settings.MAX_RETRIES,
            retry_delays=self.settings.RETRY_DELAYS_SECONDS,
        )

        # Mark mapping as failed
        if existing_mapping:
            self.order_repo.mark_failed(existing_mapping)
        else:
            self.order_repo.create(
                woo_order_id=woo_order_id,
                status=OrderStatus.FAILED,
            )

        self.db.commit()

        return OrderSyncResult(
            woo_order_id=woo_order_id,
            action="failed",
            message=str(error),
        )

    # ── Order Status Updates ─────────────────────────────────────────────

    def handle_order_cancelled(self, woo_order_id: int) -> OrderSyncResult:
        """Handle a WooCommerce order cancellation."""
        existing = self.order_repo.get_by_woo_id(woo_order_id)
        if not existing:
            return OrderSyncResult(
                woo_order_id=woo_order_id,
                action="skipped",
                message="Order not found in mappings",
            )

        if existing.odoo_order_id:
            try:
                self.odoo.execute_kw(
                    "sale.order", "action_cancel", [[existing.odoo_order_id]]
                )
                logger.info(
                    "odoo_order_cancelled",
                    woo_order_id=woo_order_id,
                    odoo_order_id=existing.odoo_order_id,
                )
            except OdooAPIError as e:
                logger.warning(
                    "odoo_order_cancel_failed",
                    odoo_order_id=existing.odoo_order_id,
                    error=str(e),
                )

        self.order_repo.mark_cancelled(existing)
        self.sync_log_repo.log_success(
            event_type="order_cancelled",
            entity_type="order",
            entity_id=str(woo_order_id),
            direction="woo_to_odoo",
            message=f"Order {woo_order_id} cancelled",
        )
        self.db.commit()

        return OrderSyncResult(
            woo_order_id=woo_order_id,
            odoo_order_id=existing.odoo_order_id,
            action="cancelled",
            message="Order cancelled",
        )

    def handle_order_refunded(self, woo_order_id: int) -> OrderSyncResult:
        """Handle a WooCommerce order refund."""
        existing = self.order_repo.get_by_woo_id(woo_order_id)
        if not existing:
            return OrderSyncResult(
                woo_order_id=woo_order_id,
                action="skipped",
                message="Order not found in mappings",
            )

        self.order_repo.mark_refunded(existing)
        self.sync_log_repo.log_success(
            event_type="order_refunded",
            entity_type="order",
            entity_id=str(woo_order_id),
            direction="woo_to_odoo",
            message=f"Order {woo_order_id} marked as refunded",
        )
        self.db.commit()

        return OrderSyncResult(
            woo_order_id=woo_order_id,
            odoo_order_id=existing.odoo_order_id,
            action="refunded",
            message="Order refund recorded",
        )
