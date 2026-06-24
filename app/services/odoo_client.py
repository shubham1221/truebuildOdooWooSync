"""
TrueBuild Integration Platform — Odoo XML-RPC Client.

Production-grade wrapper around Odoo's XML-RPC external API.
Handles authentication, reconnection, timeout, and structured logging
for all interactions with Odoo Online (SaaS).

Odoo is the MASTER system — this client reads and writes master data.
"""

from __future__ import annotations

import time
import xmlrpc.client
from typing import Any

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class OdooAPIError(Exception):
    """Raised when an Odoo XML-RPC call fails."""

    def __init__(self, message: str, model: str | None = None, method: str | None = None):
        self.model = model
        self.method = method
        super().__init__(message)


class OdooClient:
    """
    Odoo Online XML-RPC client.

    Provides a clean Pythonic interface over Odoo's xmlrpc/2 endpoints.
    Handles authentication, session management, and error recovery.

    Usage:
        client = OdooClient()
        client.authenticate()
        products = client.search_read("product.template", [], ["name", "list_price"])
    """

    def __init__(
        self,
        url: str | None = None,
        db: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int | None = None,
    ) -> None:
        settings = get_settings()
        self.url = (url or settings.ODOO_URL).rstrip("/")
        self.db = db or settings.ODOO_DB
        self.username = username or settings.ODOO_USERNAME
        self.password = password or settings.ODOO_PASSWORD
        self.timeout = timeout or settings.ODOO_TIMEOUT

        self._uid: int | None = None
        self._common: xmlrpc.client.ServerProxy | None = None
        self._models: xmlrpc.client.ServerProxy | None = None

    # ── Connection Management ────────────────────────────────────────────

    def _get_transport(self) -> xmlrpc.client.Transport:
        """Create a transport with timeout support."""
        transport = xmlrpc.client.SafeTransport() if self.url.startswith("https") else xmlrpc.client.Transport()
        transport.timeout = self.timeout
        return transport

    def _connect(self) -> None:
        """Establish XML-RPC server proxies."""
        transport = self._get_transport()
        self._common = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common",
            transport=transport,
            allow_none=True,
        )
        self._models = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object",
            transport=transport,
            allow_none=True,
        )

    def authenticate(self) -> int:
        """
        Authenticate with Odoo and return the user ID (uid).

        Raises:
            OdooAPIError: If authentication fails.
        """
        self._connect()
        try:
            uid = self._common.authenticate(self.db, self.username, self.password, {})
            if not uid:
                raise OdooAPIError(
                    f"Authentication failed for user '{self.username}' on database '{self.db}'. "
                    "Check credentials and ensure you are using the API password "
                    "(set via Settings > Users > Change Password in Odoo)."
                )
            self._uid = uid
            logger.info("odoo_authenticated", uid=uid, username=self.username, db=self.db)
            return uid
        except xmlrpc.client.Fault as e:
            raise OdooAPIError(f"Odoo authentication fault: {e.faultString}") from e
        except Exception as e:
            if isinstance(e, OdooAPIError):
                raise
            raise OdooAPIError(f"Odoo connection error: {e}") from e

    def _ensure_authenticated(self) -> None:
        """Ensure we have a valid session, re-authenticating if needed."""
        if self._uid is None or self._models is None:
            self.authenticate()

    # ── Core Execute ─────────────────────────────────────────────────────

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """
        Execute an Odoo model method via XML-RPC.

        Args:
            model: Odoo model name (e.g., 'product.template')
            method: Method name (e.g., 'search_read', 'create', 'write')
            args: Positional arguments for the method
            kwargs: Keyword arguments for the method

        Returns:
            Method result from Odoo.

        Raises:
            OdooAPIError: If the call fails.
        """
        self._ensure_authenticated()
        args = args or []
        kwargs = kwargs or {}

        start_time = time.monotonic()
        try:
            result = self._models.execute_kw(
                self.db, self._uid, self.password, model, method, args, kwargs
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.debug(
                "odoo_api_call",
                model=model,
                method=method,
                duration_ms=duration_ms,
            )
            return result
        except xmlrpc.client.Fault as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "odoo_api_fault",
                model=model,
                method=method,
                fault=e.faultString,
                duration_ms=duration_ms,
            )
            # Retry authentication on session-related errors
            if "Session" in str(e.faultString) or "Access" in str(e.faultString):
                logger.info("odoo_session_expired_reconnecting", model=model, method=method)
                self._uid = None
                self._ensure_authenticated()
                return self._models.execute_kw(
                    self.db, self._uid, self.password, model, method, args, kwargs
                )
            raise OdooAPIError(
                f"Odoo API error on {model}.{method}: {e.faultString}",
                model=model,
                method=method,
            ) from e
        except Exception as e:
            if isinstance(e, OdooAPIError):
                raise
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "odoo_api_error",
                model=model,
                method=method,
                error=str(e),
                duration_ms=duration_ms,
            )
            raise OdooAPIError(
                f"Odoo API error on {model}.{method}: {e}",
                model=model,
                method=method,
            ) from e

    # ── Convenience Methods ──────────────────────────────────────────────

    def search(
        self,
        model: str,
        domain: list[Any],
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[int]:
        """
        Search for record IDs matching the domain.

        Args:
            model: Odoo model name
            domain: Search domain filter
            limit: Max records to return
            offset: Number of records to skip
            order: Sort order (e.g., 'name asc')

        Returns:
            List of matching record IDs.
        """
        kwargs: dict[str, Any] = {"offset": offset}
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        return self.execute_kw(model, "search", [domain], kwargs)

    def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Read specific records by ID.

        Args:
            model: Odoo model name
            ids: List of record IDs to read
            fields: List of field names to return (None = all)

        Returns:
            List of record dictionaries.
        """
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        return self.execute_kw(model, "read", [ids], kwargs)

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search and read records in a single call.

        Args:
            model: Odoo model name
            domain: Search domain filter
            fields: List of field names to return
            limit: Max records to return
            offset: Number of records to skip
            order: Sort order

        Returns:
            List of record dictionaries.
        """
        kwargs: dict[str, Any] = {"offset": offset}
        if fields:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def create(self, model: str, values: dict[str, Any]) -> int:
        """
        Create a new record.

        Args:
            model: Odoo model name
            values: Dictionary of field values

        Returns:
            ID of the created record.
        """
        record_id = self.execute_kw(model, "create", [values])
        logger.info("odoo_record_created", model=model, record_id=record_id)
        return record_id

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        """
        Update existing records.

        Args:
            model: Odoo model name
            ids: List of record IDs to update
            values: Dictionary of field values to update

        Returns:
            True if successful.
        """
        result = self.execute_kw(model, "write", [ids, values])
        logger.info("odoo_record_updated", model=model, ids=ids)
        return result

    def unlink(self, model: str, ids: list[int]) -> bool:
        """
        Delete records.

        Args:
            model: Odoo model name
            ids: List of record IDs to delete

        Returns:
            True if successful.
        """
        result = self.execute_kw(model, "unlink", [ids])
        logger.info("odoo_record_deleted", model=model, ids=ids)
        return result

    def search_count(self, model: str, domain: list[Any]) -> int:
        """Count records matching the domain."""
        return self.execute_kw(model, "search_count", [domain])

    def execute(self, model: str, method: str, *args: Any) -> Any:
        """
        Execute a custom method on a model.

        Used for methods like action_confirm, _create_invoices, etc.

        Args:
            model: Odoo model name
            method: Method name
            *args: Method arguments

        Returns:
            Method result.
        """
        return self.execute_kw(model, method, list(args))

    # ── Product-Specific Helpers ─────────────────────────────────────────

    def get_product_templates(
        self,
        domain: list[Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Fetch product templates with all sync-relevant fields.

        Returns product.template records with fields needed for
        WooCommerce synchronization.
        """
        fields = [
            "name",
            "default_code",
            "description",
            "description_sale",
            "list_price",
            "standard_price",
            "categ_id",
            "image_1920",
            "barcode",
            "type",
            "active",
            "attribute_line_ids",
            "product_variant_ids",
            "product_variant_count",
            "weight",
            "taxes_id",
        ]
        return self.search_read(
            "product.template",
            domain or [["active", "=", True], ["type", "in", ["product", "consu"]]],
            fields=fields,
            limit=limit,
            offset=offset,
        )

    def get_product_variants(
        self,
        template_id: int,
    ) -> list[dict[str, Any]]:
        """
        Fetch all variants (product.product) for a given template.

        Returns variant records with SKU, price, stock, and attribute values.
        """
        fields = [
            "name",
            "default_code",
            "lst_price",
            "standard_price",
            "barcode",
            "weight",
            "qty_available",
            "product_template_attribute_value_ids",
            "image_variant_1920",
            "active",
            "product_tmpl_id",
            "categ_id",
        ]
        return self.search_read(
            "product.product",
            [["product_tmpl_id", "=", template_id], ["active", "=", True]],
            fields=fields,
        )

    def get_attribute_values(self, value_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch attribute value details (name, attribute name)."""
        if not value_ids:
            return []
        return self.search_read(
            "product.template.attribute.value",
            [["id", "in", value_ids]],
            fields=["name", "attribute_id", "product_attribute_value_id"],
        )

    def get_product_categories(
        self,
        domain: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch product categories."""
        return self.search_read(
            "product.category",
            domain or [],
            fields=["name", "parent_id", "complete_name"],
        )

    def get_stock_quantities(
        self,
        product_ids: list[int],
    ) -> list[dict[str, Any]]:
        """
        Get stock quantities for products.

        Uses stock.quant to get available quantities.
        """
        return self.search_read(
            "stock.quant",
            [
                ["product_id", "in", product_ids],
                ["location_id.usage", "=", "internal"],
            ],
            fields=["product_id", "quantity", "reserved_quantity"],
        )

    def create_partner(self, values: dict[str, Any]) -> int:
        """Create a new res.partner (customer)."""
        return self.create("res.partner", values)

    def find_partner_by_email(self, email: str) -> list[dict[str, Any]]:
        """Find a partner by email address."""
        return self.search_read(
            "res.partner",
            [["email", "=", email.lower().strip()]],
            fields=["id", "name", "email", "phone", "street", "city", "state_id", "zip", "country_id"],
            limit=1,
        )

    def create_sale_order(self, values: dict[str, Any]) -> int:
        """Create a new sale.order."""
        return self.create("sale.order", values)

    def confirm_sale_order(self, order_id: int) -> Any:
        """Confirm a sale.order (action_confirm)."""
        return self.execute_kw("sale.order", "action_confirm", [[order_id]])

    def create_invoice_from_order(self, order_id: int) -> Any:
        """
        Attempt to create an invoice from a confirmed sale order.

        Note: This calls _create_invoices via XML-RPC. On Odoo Online,
        this may fail if the method is restricted. Falls back gracefully.
        """
        try:
            result = self.execute_kw(
                "sale.order", "_create_invoices", [[order_id]]
            )
            logger.info("odoo_invoice_created", order_id=order_id, result=result)
            return result
        except OdooAPIError:
            logger.warning(
                "odoo_invoice_creation_failed",
                order_id=order_id,
                message="Invoice creation via API may not be available on Odoo Online. "
                "Create invoices manually or via Odoo automated actions.",
            )
            return None

    def post_invoice(self, invoice_id: int) -> Any:
        """Post (validate) an invoice."""
        try:
            return self.execute_kw("account.move", "action_post", [[invoice_id]])
        except OdooAPIError:
            logger.warning(
                "odoo_invoice_post_failed",
                invoice_id=invoice_id,
                message="Invoice posting via API may require additional permissions.",
            )
            return None

    # ── Health Check ─────────────────────────────────────────────────────

    def check_connection(self) -> dict[str, Any]:
        """
        Test the connection to Odoo.

        Returns:
            Dictionary with connection status and version info.
        """
        try:
            self._connect()
            version = self._common.version()
            return {
                "status": "connected",
                "server_version": version.get("server_version", "unknown"),
                "url": self.url,
                "db": self.db,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "url": self.url,
                "db": self.db,
            }
