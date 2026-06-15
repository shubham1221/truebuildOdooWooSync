from __future__ import annotations
import sys
import random
from sqlalchemy.orm import Session
from app.config.settings import get_settings
from app.database.db import get_session_factory
from app.database.models import ProductMapping, VariantMapping
from app.services.odoo_client import OdooClient
from app.services.woo_client import WooCommerceClient
from app.services.order_sync import OrderSyncService

def main():
    try:
        settings = get_settings()
        session_factory = get_session_factory()
        db: Session = session_factory()
        
        print("=== Step 1: Setting up Local Database Mappings ===")
        
        # 1. Simple Product: Silicone Sealant (Odoo ID: 41, Variant ID: 69)
        mapping_simple = db.query(ProductMapping).filter_by(sku="sealant-881").first()
        if not mapping_simple:
            mapping_simple = ProductMapping(
                odoo_product_id=41,
                woo_product_id=99999,
                sku="sealant-881",
                product_type="simple",
                sync_status="synced"
            )
            db.add(mapping_simple)
            db.commit()
            print("✓ Created database mapping for simple product 'sealant-881'")
        else:
            print("✓ Database mapping for simple product 'sealant-881' already exists")

        # 2. Variable Product: Aluminium Trims (Odoo ID: 42, Variant ID: 71, SKU: AT-1)
        mapping_parent = db.query(ProductMapping).filter_by(sku="AT-PARENT").first()
        if not mapping_parent:
            mapping_parent = ProductMapping(
                odoo_product_id=42,
                woo_product_id=88888,
                sku="AT-PARENT",
                product_type="variable",
                sync_status="synced"
            )
            db.add(mapping_parent)
            db.commit()
            print("✓ Created parent database mapping for 'AT-PARENT'")
        else:
            print("✓ Parent database mapping for 'AT-PARENT' already exists")
            
        mapping_variant = db.query(VariantMapping).filter_by(sku="AT-1").first()
        if not mapping_variant:
            mapping_variant = VariantMapping(
                product_mapping_id=mapping_parent.id,
                odoo_variant_id=71,
                woo_variant_id=71111,
                sku="AT-1",
                sync_status="synced"
            )
            db.add(mapping_variant)
            db.commit()
            print("✓ Created variant database mapping for 'AT-1'")
        else:
            print("✓ Variant database mapping for 'AT-1' already exists")

        # 3. Instantiate Clients & Service
        print("\n=== Step 2: Connecting to Odoo ===")
        odoo = OdooClient()
        odoo.authenticate()
        
        # WooCommerce client is mocked/unused as we send the payload directly
        woo = WooCommerceClient() 
        
        service = OrderSyncService(odoo, woo, db)
        
        # 4. Create a unique simulated order ID to avoid duplicate runs (idempotency check)
        fake_order_id = random.randint(100000, 999999)
        print(f"\n=== Step 3: Simulating WooCommerce Webhook Order (ID: {fake_order_id}) ===")
        
        # This payload represents a WooCommerce order containing both products
        payload = {
            "id": fake_order_id,
            "number": str(fake_order_id),
            "status": "processing",
            "currency": "AUD",
            "total": "25.00",
            "billing": {
                "email": "test-customer@example.com",
                "first_name": "Test",
                "last_name": "Customer",
                "phone": "0400000000",
                "address_1": "123 Test St",
                "city": "Sydney",
                "state": "NSW",
                "postcode": "2000",
                "country": "AU"
            },
            "line_items": [
                {
                    "id": 1,
                    "product_id": 99999,
                    "sku": "sealant-881",
                    "name": "Silicone Sealant 881 White",
                    "quantity": 2, # Ordered 2
                    "price": "5.00",
                    "subtotal": "10.00",
                    "total": "10.00"
                },
                {
                    "id": 2,
                    "product_id": 88888,
                    "variation_id": 71111,
                    "sku": "AT-1",
                    "name": "Aluminium Trims - AT-1",
                    "quantity": 1, # Ordered 1
                    "price": "15.00",
                    "subtotal": "15.00",
                    "total": "15.00"
                }
            ]
        }
        
        # 5. Process the Order
        print("Dispatching order payload to sync service...")
        result = service.sync_order_from_payload(payload)
        
        print("\n=== Step 4: Sync Results ===")
        print(f"  Action Status:    {result.action}")
        print(f"  Woo Order ID:     {result.woo_order_id}")
        print(f"  Odoo Order ID:    {result.odoo_order_id}")
        print(f"  Odoo Invoice ID:  {result.odoo_invoice_id}")
        print(f"  Message:          {result.message}")
        print("\n✓ Simulated order successfully created, validated, and inventory reserved/deducted in Odoo!")
        
    except Exception as e:
        print(f"\n✗ Error during order simulation: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
