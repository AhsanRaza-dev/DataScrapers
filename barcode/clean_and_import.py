import gzip
import json
import re
import os
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

# Load environment variables
load_dotenv(r'd:\curiologix\barcode\.env')

# Configuration
BRAND_FILE = r'd:\curiologix\barcode\brand.json'
INPUT_FILE = r'd:\curiologix\barcode\openfoodfacts-products.jsonl.gz'

# DB Config
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def setup_database(conn):
    """Create the new table."""
    create_table_query = """
    DROP TABLE IF EXISTS product_catalog;
    CREATE TABLE product_catalog (
        id SERIAL PRIMARY KEY,
        barcode TEXT,
        product_name TEXT,
        brand_name TEXT,
        category TEXT,
        pos_metadata JSONB,
        sources JSONB,
        countries JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_cat_barcode ON product_catalog(barcode);
    CREATE INDEX IF NOT EXISTS idx_cat_brand ON product_catalog(brand_name);
    """
    with conn.cursor() as cur:
        cur.execute(create_table_query)
    conn.commit()

def load_brands(filepath):
    if not os.path.exists(filepath):
        print(f"Error: Brand file '{filepath}' not found.")
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if "grocery_brands_pakistan" in data:
            return [b.strip() for b in data["grocery_brands_pakistan"] if b.strip()]
        return []

def transform_product(raw_data, brand_name):
    """
    Transforms raw OFF data into the requested local schema.
    """
    code = raw_data.get('code', '')
    
    # Robust name extraction
    product_name = raw_data.get('product_name', '')
    if not product_name:
        product_name = raw_data.get('product_name_en', '')
    if not product_name:
        product_name = raw_data.get('product_name_ur', '')
    if not product_name:
        product_name = raw_data.get('generic_name', '')
    if not product_name:
         qty = raw_data.get('quantity', '')
         if qty:
             product_name = f"{brand_name} Product ({qty})"
         else:
             product_name = "Unknown Product"

    categories_str = raw_data.get('categories', '')
    
    # Heuristics
    categories_tags = raw_data.get('categories_tags', [])
    clean_cats = [c.lower() for c in categories_tags]
    
    is_beverage = False
    for tag in clean_cats:
        if 'beverage' in tag or 'drink' in tag:
            is_beverage = True
            break
            
    # Broad Categorization Logic
    main_category = "Other"
    
    if any(k in str(clean_cats) for k in ['beverage', 'drink', 'juice', 'soda', 'water', 'tea', 'coffee', 'milk']):
        main_category = "Beverage"
    elif any(k in str(clean_cats) for k in ['snack', 'chip', 'crisp', 'biscuit', 'cookie', 'cracker', 'chocolate', 'candy', 'sweet']):
        main_category = "Snack"
    elif any(k in str(clean_cats) for k in ['dairy', 'cheese', 'yogurt', 'butter', 'cream']):
        main_category = "Dairy"
    elif any(k in str(clean_cats) for k in ['sauce', 'condiment', 'dressing', 'ketchup', 'mayonnaise', 'spice']):
        main_category = "Condiment/Sauce"
    elif any(k in str(clean_cats) for k in ['meat', 'chicken', 'beef', 'poultry', 'seafood', 'fish']):
        main_category = "Meat/Seafood"
    elif any(k in str(clean_cats) for k in ['bread', 'bakery', 'cereal', 'wheat', 'grain', 'pasta', 'rice']):
        main_category = "Bakery/Grain"
    elif any(k in str(clean_cats) for k in ['fruit', 'vegetable', 'plant-based']):
        main_category = "Produce"
    elif any(k in str(clean_cats) for k in ['frozen', 'ice cream']):
        main_category = "Frozen"
    elif any(k in str(clean_cats) for k in ['meal', 'prepared']):
        main_category = "Prepared Meal"
    elif any(k in str(clean_cats) for k in ['baby', 'infant']):
        main_category = "Baby Food"
    elif any(k in str(clean_cats) for k in ['pet', 'cat', 'dog']):
        main_category = "Pet Food"
    elif any(k in str(clean_cats) for k in ['clean', 'detergent', 'soap', 'hygiene', 'wash']):
        main_category = "Household/Hygiene"
    elif categories_tags:
        first_cat = categories_tags[0].replace('en:', '').replace('-', ' ').title()
        if len(first_cat) < 30:
            main_category = first_cat

    manufacturer = raw_data.get('manufacturing_places', '')
    if not manufacturer:
        manufacturer = raw_data.get('brands', '')

    ingredients = raw_data.get('ingredients_text', '') or raw_data.get('ingredients_text_en', '')

    nova = raw_data.get('nova_group')
    serving = raw_data.get('serving_size', '')
    
    pos_metadata = {
        "internal_id": code,
        "display_name": product_name,
        "brand": brand_name,
        "manufacturer": manufacturer,
        "category_path": categories_str,
        "ingredients": ingredients,
        "attributes": {
            "nova_group": nova,
            "is_beverage": is_beverage,
            "serving_size": serving
        }
    }

    return {
        "barcode": code,
        "product_name": product_name,
        "brand_name": brand_name,
        "category": main_category,
        "pos_metadata": json.dumps(pos_metadata),
        "sources": json.dumps(raw_data.get('sources', [])),
        "countries": json.dumps(raw_data.get('countries_tags', []))
    }

def main():
    print("Starting Data Cleaning Pipeline...")
    
    # 1. Load Brands
    brands = load_brands(BRAND_FILE)
    if not brands:
        return

    # 2. DB Setup
    conn = get_db_connection()
    if not conn:
        return
    setup_database(conn)
    print("Database ready.")

    # 3. Compile Regex
    escaped_brands = [re.escape(b) for b in brands]
    pattern_str = r'\b(' + '|'.join(escaped_brands) + r')\b'
    try:
        brand_pattern = re.compile(pattern_str, re.IGNORECASE)
    except re.error as e:
        print(f"Regex Error: {e}")
        return

    # 4. Process
    normalized_brands = {b.lower(): b for b in brands}
    batch_size = 1000
    batch_buffer = []

    insert_query = """
        INSERT INTO product_catalog 
        (barcode, product_name, brand_name, category, pos_metadata, sources, countries)
        VALUES (%(barcode)s, %(product_name)s, %(brand_name)s, %(category)s, %(pos_metadata)s, %(sources)s, %(countries)s)
    """

    scanned_count = 0
    matched_count = 0

    try:
        # Check if file exists
        if not os.path.exists(INPUT_FILE):
             print("Input file not found.")
             return

        with gzip.open(INPUT_FILE, 'rt', encoding='utf-8') as f_in:
            for line in f_in:
                scanned_count += 1
                if scanned_count % 50000 == 0:
                    print(f"Scanned {scanned_count} lines... Mapped {matched_count} products.")

                try:
                    product = json.loads(line)
                    product_brands = product.get('brands', '')
                    
                    if not product_brands:
                        continue
                    
                    matches = brand_pattern.findall(product_brands)
                    
                    if matches:
                        unique_matches = set(m.lower() for m in matches)
                        for m in unique_matches:
                            if m in normalized_brands:
                                canonical_name = normalized_brands[m]
                                
                                # Transform
                                clean_record = transform_product(product, canonical_name)
                                batch_buffer.append(clean_record)
                                matched_count += 1
                        
                        if len(batch_buffer) >= batch_size:
                            with conn.cursor() as cur:
                                execute_batch(cur, insert_query, batch_buffer)
                            conn.commit()
                            batch_buffer = []
                            
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"Error on line {scanned_count}: {e}")
                    conn.rollback()

        # Final Batch
        if batch_buffer:
            with conn.cursor() as cur:
                execute_batch(cur, insert_query, batch_buffer)
            conn.commit()

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        conn.close()
        print(f"Done. Total Scanned: {scanned_count}. Total Mapped: {matched_count}.")

if __name__ == "__main__":
    main()
