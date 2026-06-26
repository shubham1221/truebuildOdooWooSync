"""
Live Order Test — Verify clean address display in Odoo.
New customer so we get fresh contacts with the fixed naming.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config.settings import get_settings
from app.database.db import get_session_factory
from app.database.models import ProductMapping
from app.services.woo_client import WooCommerceClient
from app.services.odoo_client import OdooClient
from app.services.order_sync import OrderSyncService


def main():
    print("=" * 70)
    print("  LIVE ORDER TEST — Clean Address Display")
    print("=" * 70)

    woo = WooCommerceClient()
    odoo = OdooClient()
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        mapping = db.query(ProductMapping).filter(
            ProductMapping.woo_product_id.isnot(None),
            ProductMapping.sku.isnot(None),
            ProductMapping.sku != "",
        ).first()

        if not mapping:
            print("  ✗ No synced products found.")
            return

        print(f"\n  Using product: SKU={mapping.sku}, WooID={mapping.woo_product_id}")

        # Create order with a completely new customer
        print("\n[1/3] Creating WooCommerce order...")
        order_data = {
            "payment_method": "cheque",
            "payment_method_title": "Check payments",
            "set_paid": True,
            "status": "processing",
            "billing": {
                "first_name": "Sarah",
                "last_name": "Mitchell",
                "company": "",
                "address_1": "77 Pitt Street",
                "address_2": "Unit 4",
                "city": "Sydney",
                "state": "NSW",
                "postcode": "2000",
                "country": "AU",
                "email": "sarah.mitchell.test@truebuild.com.au",
                "phone": "+61 411 222 333",
            },
            "shipping": {
                "first_name": "Sarah",
                "last_name": "Mitchell",
                "company": "",
                "address_1": "120 Queen Street",
                "address_2": "",
                "city": "Brisbane",
                "state": "QLD",
                "postcode": "4000",
                "country": "AU",
                "phone": "+61 411 444 555",
            },
            "line_items": [{"product_id": mapping.woo_product_id, "quantity": 1}],
        }

        woo_order = woo.post("orders", order_data)
        woo_id = woo_order["id"]
        print(f"  ✓ Order #{woo_order.get('number')} created (ID: {woo_id})")

        # Sync to Odoo
        print("\n[2/3] Syncing to Odoo...")
        result = OrderSyncService(odoo, woo, db).sync_order_from_payload(woo_order)
        print(f"  Action: {result.action} | {result.message}")

        if result.action == "failed":
            print(f"\n  ✗ FAILED")
            return

        # Verify
        print(f"\n[3/3] Verifying in Odoo (Sale Order ID: {result.odoo_order_id})...")
        so = odoo.search_read(
            "sale.order",
            [["id", "=", result.odoo_order_id]],
            fields=["name", "partner_id", "partner_invoice_id", "partner_shipping_id"],
            limit=1,
        )[0]

        pid = so["partner_id"][0] if isinstance(so["partner_id"], (list, tuple)) else so["partner_id"]
        iid = so["partner_invoice_id"][0] if isinstance(so["partner_invoice_id"], (list, tuple)) else so["partner_invoice_id"]
        sid = so["partner_shipping_id"][0] if isinstance(so["partner_shipping_id"], (list, tuple)) else so["partner_shipping_id"]

        partners = odoo.search_read(
            "res.partner",
            [["id", "in", list(set([pid, iid, sid]))]],
            fields=["id", "name", "type", "street", "city", "state_id", "zip", "parent_id"],
        )
        pmap = {p["id"]: p for p in partners}

        print(f"\n  Sale Order: {so.get('name')}")

        # Customer display
        p = pmap.get(pid, {})
        print(f"\n  Customer (ID={pid}):")
        print(f"    Name:    {p.get('name')}")
        print(f"    Street:  {p.get('street', 'none')}")
        print(f"    City:    {p.get('city', 'none')}")
        has_addr = bool(p.get('street') or p.get('city'))
        print(f"    → {'⚠ Has address (should be name only)' if has_addr else '✓ Name only — no address'}")

        # Invoice display
        i = pmap.get(iid, {})
        parent_name = p.get('name', '')
        child_name = i.get('name', '')
        display = f"{parent_name}, {child_name}" if parent_name != child_name else f"{parent_name}, {child_name} (DUPLICATE!)"
        print(f"\n  Invoice Address (ID={iid}):")
        print(f"    Child Name: {child_name}")
        print(f"    Odoo shows: {display}")
        print(f"    Street:     {i.get('street', '-')}")
        print(f"    City:       {i.get('city', '-')}")

        # Delivery display
        d = pmap.get(sid, {})
        child_name_d = d.get('name', '')
        display_d = f"{parent_name}, {child_name_d}"
        print(f"\n  Delivery Address (ID={sid}):")
        print(f"    Child Name: {child_name_d}")
        print(f"    Odoo shows: {display_d}")
        print(f"    Street:     {d.get('street', '-')}")
        print(f"    City:       {d.get('city', '-')}")

        print(f"\n{'=' * 70}")
        print(f"  ✓ DONE — Check Odoo Sale Order {so.get('name')}")
        print(f"{'=' * 70}")

    except Exception as e:
        print(f"\n  ✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
        woo.close()


if __name__ == "__main__":
    main()
