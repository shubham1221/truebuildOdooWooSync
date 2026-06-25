"""
TrueBuild Integration Platform — Customer Sync Service.

Handles customer matching and creation in Odoo.
Customers from WooCommerce orders are matched by email.
If no existing partner is found in Odoo, a new res.partner is created.

Address Mapping:
    - One parent customer (type=contact) is created/found per email.
    - One billing child contact (type=invoice) under the parent.
    - One shipping child contact (type=delivery) under the parent.
    - Sale Orders are assigned all three IDs explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.customer_repo import CustomerMappingRepository
from app.repositories.sync_log_repo import SyncLogRepository
from app.schemas.customer import CustomerData
from app.services.odoo_client import OdooClient
from app.utils.logging import get_logger

logger = get_logger(__name__)


# ── Data Transfer Objects ────────────────────────────────────────────────


@dataclass(frozen=True)
class AddressData:
    """Address data extracted from a WooCommerce billing or shipping block."""

    first_name: str = ""
    last_name: str = ""
    company: str = ""
    address_1: str = ""
    address_2: str = ""
    city: str = ""
    state: str = ""
    postcode: str = ""
    country: str = "AU"
    email: str = ""
    phone: str = ""


@dataclass(frozen=True)
class PartnerAddressResult:
    """IDs for all three partner references on a sale.order."""

    partner_id: int  # Parent customer (type=contact)
    partner_invoice_id: int  # Billing child (type=invoice)
    partner_shipping_id: int  # Shipping child (type=delivery)


class CustomerSyncService:
    """
    Matches or creates customers in Odoo from WooCommerce order data.

    Matching priority:
    1. Check local CustomerMapping table by email
    2. Search Odoo res.partner by email (type=contact only)
    3. Create new res.partner if not found

    After finding/creating the parent, billing and shipping child contacts
    are created or updated under the parent.

    Email is the canonical matching key.
    """

    def __init__(
        self,
        odoo: OdooClient,
        db: Session,
    ) -> None:
        self.odoo = odoo
        self.db = db
        self.customer_repo = CustomerMappingRepository(db)
        self.sync_log_repo = SyncLogRepository(db)

    # ── Public API ───────────────────────────────────────────────────────

    def get_or_create_partner(
        self,
        customer: CustomerData,
        billing_address: AddressData,
        shipping_address: AddressData,
    ) -> PartnerAddressResult:
        """
        Get or create an Odoo partner with billing and shipping child contacts.

        Args:
            customer: Core customer data (email, name) for the parent contact.
            billing_address: Full billing address from WooCommerce.
            shipping_address: Full shipping address from WooCommerce.

        Returns:
            PartnerAddressResult with partner_id, partner_invoice_id,
            and partner_shipping_id.
        """
        email = customer.email.lower().strip()
        if not email:
            raise ValueError("Customer email is required for matching")

        # ── Find or create parent customer ───────────────────────────
        parent_id = self._find_or_create_parent(customer, email)

        # ── Find or create billing child (type=invoice) ──────────────
        invoice_id = self._get_or_create_child_contact(
            parent_id=parent_id,
            address=billing_address,
            contact_type="invoice",
        )
        logger.info(
            "billing_contact_resolved",
            parent_id=parent_id,
            invoice_contact_id=invoice_id,
        )

        # ── Find or create shipping child (type=delivery) ────────────
        delivery_id = self._get_or_create_child_contact(
            parent_id=parent_id,
            address=shipping_address,
            contact_type="delivery",
        )
        logger.info(
            "shipping_contact_resolved",
            parent_id=parent_id,
            delivery_contact_id=delivery_id,
        )

        return PartnerAddressResult(
            partner_id=parent_id,
            partner_invoice_id=invoice_id,
            partner_shipping_id=delivery_id,
        )

    # ── Parent Customer ──────────────────────────────────────────────────

    def _find_or_create_parent(
        self,
        customer: CustomerData,
        email: str,
    ) -> int:
        """Find an existing parent customer or create a new one."""

        # 1. Check local mapping
        mapping = self.customer_repo.get_by_email(email)
        if mapping:
            logger.info(
                "customer_found_in_mapping",
                email=email,
                odoo_partner_id=mapping.odoo_partner_id,
            )
            return mapping.odoo_partner_id

        # 2. Search Odoo by email (type=contact only)
        odoo_partners = self.odoo.find_partner_by_email(email)
        if odoo_partners:
            partner = odoo_partners[0]
            partner_id = partner["id"]
            logger.info(
                "customer_found_in_odoo",
                email=email,
                odoo_partner_id=partner_id,
            )
            # Create local mapping
            self.customer_repo.create(
                odoo_partner_id=partner_id,
                email=email,
                woo_customer_id=customer.woo_customer_id,
                first_name=customer.first_name,
                last_name=customer.last_name,
            )
            self.sync_log_repo.log_success(
                event_type="customer_matched",
                entity_type="customer",
                entity_id=email,
                direction="woo_to_odoo",
                message=f"Matched existing Odoo partner {partner_id}",
            )
            return partner_id

        # 3. Create new parent partner in Odoo
        partner_id = self._create_parent(customer)
        logger.info(
            "customer_created_in_odoo",
            email=email,
            odoo_partner_id=partner_id,
        )

        # Create local mapping
        self.customer_repo.create(
            odoo_partner_id=partner_id,
            email=email,
            woo_customer_id=customer.woo_customer_id,
            first_name=customer.first_name,
            last_name=customer.last_name,
        )
        self.sync_log_repo.log_success(
            event_type="customer_created",
            entity_type="customer",
            entity_id=email,
            direction="woo_to_odoo",
            message=f"Created new Odoo partner {partner_id} for {email}",
        )
        return partner_id

    def _create_parent(self, customer: CustomerData) -> int:
        """Create a new parent res.partner (type=contact) in Odoo."""
        name_parts = [customer.first_name, customer.last_name]
        name = " ".join(p for p in name_parts if p).strip()
        if not name:
            name = customer.email

        values: dict[str, Any] = {
            "name": name,
            "email": customer.email.lower().strip(),
            "customer_rank": 1,
            "type": "contact",
        }

        if customer.phone:
            values["phone"] = customer.phone
        if customer.company:
            values["company_type"] = "company"
            values["name"] = customer.company

        return self.odoo.create_partner(values)

    # ── Child Contacts (Billing / Shipping) ──────────────────────────────

    def _get_or_create_child_contact(
        self,
        parent_id: int,
        address: AddressData,
        contact_type: str,
    ) -> int:
        """
        Find or create a child contact under the parent.

        Args:
            parent_id: Odoo res.partner ID of the parent customer.
            address: Address data to write on the child contact.
            contact_type: Odoo address type — 'invoice' or 'delivery'.

        Returns:
            Odoo res.partner ID of the child contact.
        """
        type_label = "billing" if contact_type == "invoice" else "shipping"

        try:
            # Search for existing child contact
            existing = self.odoo.search_read(
                "res.partner",
                [
                    ["parent_id", "=", parent_id],
                    ["type", "=", contact_type],
                ],
                fields=["id"],
                limit=1,
            )

            address_values = self._build_address_values(address, contact_type, parent_id)

            if existing:
                child_id = existing[0]["id"]
                # Update existing child with latest address data
                self.odoo.write("res.partner", [child_id], address_values)
                logger.info(
                    "child_contact_updated",
                    parent_id=parent_id,
                    child_id=child_id,
                    contact_type=contact_type,
                )
                return child_id

            # Create new child contact
            child_id = self.odoo.create_partner(address_values)
            logger.info(
                "child_contact_created",
                parent_id=parent_id,
                child_id=child_id,
                contact_type=contact_type,
            )
            return child_id

        except Exception as e:
            logger.error(
                "child_contact_failed",
                parent_id=parent_id,
                contact_type=contact_type,
                error=str(e),
                exc_info=True,
            )
            raise ValueError(
                f"Failed to create/update {type_label} contact for "
                f"parent {parent_id}: {e}"
            ) from e

    def _build_address_values(
        self,
        address: AddressData,
        contact_type: str,
        parent_id: int,
    ) -> dict[str, Any]:
        """
        Build Odoo field values for a billing or shipping child contact.

        Maps all WooCommerce address fields to their Odoo equivalents.
        """
        # Build display name
        name_parts = [address.first_name, address.last_name]
        name = " ".join(p for p in name_parts if p).strip()
        if not name:
            name = address.company or "Address"

        # Append suffix to differentiate child contacts in Odoo UI
        if contact_type == "invoice":
            name = f"{name} (Billing Contact)"
        elif contact_type == "delivery":
            name = f"{name} (Shipping Contact)"

        values: dict[str, Any] = {
            "parent_id": parent_id,
            "type": contact_type,
            "name": name,
        }

        # Street address
        if address.address_1:
            values["street"] = address.address_1
        if address.address_2:
            values["street2"] = address.address_2

        # City, ZIP
        if address.city:
            values["city"] = address.city
        if address.postcode:
            values["zip"] = address.postcode

        # Contact info
        if address.phone:
            values["phone"] = address.phone
        if address.email:
            values["email"] = address.email

        # Company name on the contact (not company_type)
        if address.company:
            values["company_name"] = address.company

        # State (resolve code → Odoo ID)
        if address.state:
            state_id = self._find_state(
                address.state,
                address.country or "AU",
            )
            if state_id:
                values["state_id"] = state_id

        # Country (resolve code → Odoo ID)
        country_code = address.country or "AU"
        country_id = self._find_country(country_code)
        if country_id:
            values["country_id"] = country_id

        return values

    # ── Geo Lookups ──────────────────────────────────────────────────────

    def _find_country(self, country_code: str) -> int | None:
        """Find Odoo country ID by ISO code."""
        try:
            countries = self.odoo.search_read(
                "res.country",
                [["code", "=", country_code.upper()]],
                fields=["id"],
                limit=1,
            )
            return countries[0]["id"] if countries else None
        except Exception:
            return None

    def _find_state(self, state_code: str, country_code: str = "AU") -> int | None:
        """Find Odoo state ID by code."""
        try:
            states = self.odoo.search_read(
                "res.country.state",
                [
                    ["code", "=", state_code.upper()],
                    ["country_id.code", "=", country_code.upper()],
                ],
                fields=["id"],
                limit=1,
            )
            return states[0]["id"] if states else None
        except Exception:
            return None
