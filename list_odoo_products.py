from __future__ import annotations
import sys
from app.config.settings import get_settings
from app.services.odoo_client import OdooClient

def main():
    try:
        settings = get_settings()
        print(f"Connecting to Odoo at: {settings.ODOO_URL}")
        print(f"Database: {settings.ODOO_DB}")
        print(f"Username: {settings.ODOO_USERNAME}")
        
        client = OdooClient()
        uid = client.authenticate()
        print(f"✓ Authentication successful! UID: {uid}")
        
        print("\nFetching product templates (up to 50)...")
        # Fetch active products of type 'product' (storable) or 'consu' (consumable)
        products = client.get_product_templates(limit=50)
        print(f"Found {len(products)} active products in Odoo:\n")
        
        if not products:
            print("No active product templates found in Odoo.")
            return

        # Print header
        print(f"{'ID':<6} | {'SKU (Default Code)':<20} | {'Name':<35} | {'Price':<10} | {'Type':<10}")
        print("-" * 90)
        for p in products:
            sku = p.get("default_code") or "N/A"
            name = p.get("name") or "Unnamed"
            price = p.get("list_price") or 0.0
            p_type = p.get("type") or "N/A"
            p_id = p.get("id")
            
            # Truncate name for printing
            if len(name) > 32:
                name = name[:29] + "..."
            
            print(f"{p_id:<6} | {sku:<20} | {name:<35} | ${price:<9.2f} | {p_type:<10}")

    except Exception as e:
        print(f"\n✗ Error connecting to Odoo or fetching products: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
