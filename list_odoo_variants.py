from __future__ import annotations
import sys
from app.config.settings import get_settings
from app.services.odoo_client import OdooClient

def main():
    try:
        settings = get_settings()
        print(f"Connecting to Odoo at: {settings.ODOO_URL}")
        
        client = OdooClient()
        uid = client.authenticate()
        print(f"✓ Authentication successful! UID: {uid}\n")
        
        print("Fetching product templates...")
        templates = client.get_product_templates()
        print(f"Found {len(templates)} active product templates in Odoo.\n")
        
        for t in templates:
            t_id = t.get("id")
            t_name = t.get("name")
            t_sku = t.get("default_code") or "N/A"
            variant_count = t.get("product_variant_count") or 1
            variant_ids = t.get("product_variant_ids") or []
            
            print(f"Template ID: {t_id} | Name: {t_name} | SKU: {t_sku} | Variants: {variant_count}")
            
            # If the template has variants, fetch and print details
            if len(variant_ids) >= 1:
                variants = client.get_product_variants(t_id)
                for v in variants:
                    v_id = v.get("id")
                    v_sku = v.get("default_code") or "N/A"
                    v_price = v.get("lst_price") or 0.0
                    v_name = v.get("name") or "Unnamed"
                    print(f"  └── Variant ID: {v_id} | SKU: {v_sku} | Price: ${v_price:.2f} | Name: {v_name}")
            print("-" * 70)

    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
