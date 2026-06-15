"""
TrueBuild Integration Platform — Customer Sync Service.

Handles customer matching and creation in Odoo.
Customers from WooCommerce orders are matched by email.
If no existing partner is found in Odoo, a new res.partner is created.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories.customer_repo import CustomerMappingRepository
from app.repositories.sync_log_repo import SyncLogRepository
from app.schemas.customer import CustomerData
from app.services.odoo_client import OdooClient
from app.utils.logging import get_logger

logger = get_logger(__name__)


class CustomerSyncService:
    """
    Matches or creates customers in Odoo from WooCommerce order data.

    Matching priority:
    1. Check local CustomerMapping table by email
    2. Search Odoo res.partner by email
    3. Create new res.partner if not found

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

    def get_or_create_partner(self, customer: CustomerData) -> int:
        """
        Get or create an Odoo partner for a WooCommerce customer.

        Args:
            customer: Customer data from WooCommerce order.

        Returns:
            Odoo res.partner ID.
        """
        email = customer.email.lower().strip()
        if not email:
            raise ValueError("Customer email is required for matching")

        # 1. Check local mapping
        mapping = self.customer_repo.get_by_email(email)
        if mapping:
            logger.info(
                "customer_found_in_mapping",
                email=email,
                odoo_partner_id=mapping.odoo_partner_id,
            )
            # Update partner in Odoo with latest data
            self._update_partner_if_needed(mapping.odoo_partner_id, customer)
            return mapping.odoo_partner_id

        # 2. Search Odoo by email
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
            # Update with latest data
            self._update_partner_if_needed(partner_id, customer)

            self.sync_log_repo.log_success(
                event_type="customer_matched",
                entity_type="customer",
                entity_id=email,
                direction="woo_to_odoo",
                message=f"Matched existing Odoo partner {partner_id}",
            )
            return partner_id

        # 3. Create new partner in Odoo
        partner_id = self._create_partner(customer)
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

    def _create_partner(self, customer: CustomerData) -> int:
        """Create a new res.partner in Odoo."""
        # Build partner name
        name_parts = [customer.first_name, customer.last_name]
        name = " ".join(p for p in name_parts if p).strip()
        if not name:
            name = customer.email

        # Build partner values
        values: dict[str, Any] = {
            "name": name,
            "email": customer.email.lower().strip(),
            "customer_rank": 1,
            "type": "contact",
        }

        # Optional fields
        if customer.phone:
            values["phone"] = customer.phone
        if customer.company:
            values["company_type"] = "company"
            values["name"] = customer.company
        if customer.address_1:
            values["street"] = customer.address_1
        if customer.address_2:
            values["street2"] = customer.address_2
        if customer.city:
            values["city"] = customer.city
        if customer.postcode:
            values["zip"] = customer.postcode

        # State (Australian states)
        if customer.state:
            state = self._find_state(customer.state, customer.country)
            if state:
                values["state_id"] = state

        # Country (default: Australia)
        country_id = self._find_country(customer.country or "AU")
        if country_id:
            values["country_id"] = country_id

        return self.odoo.create_partner(values)

    def _update_partner_if_needed(
        self,
        partner_id: int,
        customer: CustomerData,
    ) -> None:
        """Update partner in Odoo with latest data from WooCommerce."""
        values: dict[str, Any] = {}

        if customer.phone:
            values["phone"] = customer.phone
        if customer.address_1:
            values["street"] = customer.address_1
        if customer.address_2:
            values["street2"] = customer.address_2
        if customer.city:
            values["city"] = customer.city
        if customer.postcode:
            values["zip"] = customer.postcode

        if values:
            try:
                self.odoo.write("res.partner", [partner_id], values)
                logger.debug("customer_updated_in_odoo", partner_id=partner_id)
            except Exception as e:
                logger.warning(
                    "customer_update_failed",
                    partner_id=partner_id,
                    error=str(e),
                )

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
