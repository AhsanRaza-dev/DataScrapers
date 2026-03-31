import gzip
import json
import os
import argparse
import psycopg2
from psycopg2.extras import execute_batch, execute_values
from psycopg2 import sql
from dotenv import load_dotenv

# Load environment variables
load_dotenv(r'd:\curiologix\barcode\.env')

# Configuration
INPUT_FILE = r'd:\curiologix\barcode\openfoodfacts-products.jsonl.gz'

# DB Config
DB_NAME = "open-food-facts-country-vise"
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

print(f"DEBUG: Connecting to DB '{DB_NAME}' as '{DB_USER}' at '{DB_HOST}:{DB_PORT}'")
print(f"DEBUG: Password is {'SET' if DB_PASSWORD else 'NOT SET'}")

def get_db_connection():
    # 1. First connect to default postgres to find the real DB name
    target_db_prefix = "country-vise" # Simpler prefix matching
    real_db_name = None
    
    try:
        # Use simple args to connect to default
        conn = psycopg2.connect(
            dbname="postgres",
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        with conn.cursor() as cur:
            cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false")
            rows = cur.fetchall()
            all_dbs = [r[0] for r in rows]
            print(f"DEBUG: Found databases: {all_dbs}")
            
            for db in all_dbs:
                if target_db_prefix in db:
                    real_db_name = db
                    print(f"MATCH FOUND: '{db}' contains '{target_db_prefix}'")
                    break
        conn.close()
    except Exception as e:
        print(f"Discovery Error: {e}")
        # Fallback to hardcoded if discovery fails (might fail if postgres db is locked/unreachable)
        real_db_name = target_db_prefix # Optimistic fallback

    if not real_db_name:
        print("Could not find database.")
        return None

    # 2. Connect to the discovered DB
    try:
        conn = psycopg2.connect(
            dbname=real_db_name,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database '{real_db_name}': {e}")
        return None

def setup_database(conn):
    """Create the shared common tables if they don't exist."""
    print(f"Setting up common tables: products, product_countries, product_sources")
    
    # Drop existing table to enforce schema change
    drop_query = "DROP TABLE IF EXISTS products CASCADE;"
    
    query = """
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        barcode TEXT UNIQUE,
        product_name TEXT,
        brand_name TEXT,
        manufacturer TEXT,
        main_category TEXT,
        category_path TEXT,
        serving_size TEXT
    );
    
    CREATE TABLE IF NOT EXISTS product_countries (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
        country_tag TEXT,
        UNIQUE(product_id, country_tag)
    );
    
    CREATE TABLE IF NOT EXISTS product_sources (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
        source_url TEXT,
        source_id TEXT,
        import_t BIGINT
    );

    CREATE INDEX IF NOT EXISTS idx_p_name ON products(product_name);
    CREATE INDEX IF NOT EXISTS idx_p_brand ON products(brand_name);
    CREATE INDEX IF NOT EXISTS idx_c_pid ON product_countries(product_id);
    CREATE INDEX IF NOT EXISTS idx_s_pid ON product_sources(product_id);
    """
    
    with conn.cursor() as cur:
        # We perform the DROP only if we really mean to reset. 
        # Since schema changed, we MUST reset or ALTER. Reset is cleaner for import script.
        cur.execute(drop_query) 
        cur.execute(query)
    conn.commit()

def transform_product(raw_data):
    """
    Transforms raw OFF data into the normalized schema structure.
    Returns a dict with 'main', 'countries', 'sources'.
    """
    code = raw_data.get('code', '')
    
    # Brands extraction
    brand_name = "Unknown"
    brands_tags = raw_data.get('brands_tags', [])
    if brands_tags:
        brand_name = brands_tags[0].replace('en:', '').replace('-', ' ').title()
    else:
        raw_b = raw_data.get('brands', '')
        if raw_b:
            brand_name = raw_b.split(',')[0].strip()

    # Robust name extraction
    product_name = raw_data.get('product_name', '')
    if not product_name:
        product_name = raw_data.get('product_name_en', '')
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
    
    # is_beverage removed
            
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

    # nova removed
    serving = raw_data.get('serving_size', '')
    
    # Flattened Main Data
    main_data = {
        "barcode": code,
        "product_name": product_name,
        "brand_name": brand_name,
        "manufacturer": manufacturer,
        "main_category": main_category,
        "category_path": categories_str,
        "serving_size": serving
    }
    
    # Related Data
    countries_data = raw_data.get('countries_tags', [])
    sources_data = raw_data.get('sources', [])

    return {
        "main": main_data,
        "countries": countries_data,
        "sources": sources_data
    }

def main():
    parser = argparse.ArgumentParser(description='Import products for a specific country (Common Table).')
    parser.add_argument('table_suffix', help='Ignored (legacy arg compatibility)', nargs='?') 
    parser.add_argument('--tags', nargs='+', required=True, help='Country tags to match (e.g., "en:united-states" "us")')
    
    args = parser.parse_args()
    
    country_tags = [t.lower() for t in args.tags]
    
    print(f"Starting Import for tags: {country_tags} into COMMON tables.")
    
    conn = get_db_connection()
    if not conn:
        return
    setup_database(conn)
    
    batch_size = 1000
    batch_buffer = []

    # UPSERT Query for products
    # If barcode collision, we technically just want the ID. We can do DO UPDATE SET id=id to enable RETURNING.
    # But usually we might want to fill in potentially missing nulls? 
    # For now, simplistic approach: conflicts updates nothing but ensures we get the ID back.
    insert_product_sql = """
        INSERT INTO products 
        (barcode, product_name, brand_name, manufacturer, main_category, category_path, serving_size)
        VALUES %s
        ON CONFLICT (barcode) DO UPDATE 
            SET product_name = EXCLUDED.product_name 
        RETURNING id
    """

    insert_countries_sql = """
        INSERT INTO product_countries (product_id, country_tag) VALUES %s
        ON CONFLICT (product_id, country_tag) DO NOTHING
    """

    insert_sources_sql = """
        INSERT INTO product_sources (product_id, source_url, source_id, import_t) VALUES %s
    """

    scanned_count = 0
    imported_count = 0

    try:
        if not os.path.exists(INPUT_FILE):
             print("Input file not found.")
             return

        with gzip.open(INPUT_FILE, 'rt', encoding='utf-8') as f_in:
            for line in f_in:
                scanned_count += 1
                if scanned_count % 50000 == 0:
                    print(f"Scanned {scanned_count} lines... Imported {imported_count} products.")

                try:
                    product = json.loads(line)
                    
                    # Country Check
                    p_countries = product.get('countries_tags', [])
                    if not p_countries:
                        continue
                        
                    p_tags_lower = set(c.lower() for c in p_countries)
                    is_match = False
                    for tag in country_tags:
                         if tag in p_tags_lower:
                             is_match = True
                             break
                    
                    if not is_match:
                        continue
                        
                    # Transform
                    clean_record = transform_product(product)
                    batch_buffer.append(clean_record)
                    imported_count += 1
                    
                    if len(batch_buffer) >= batch_size:
                        # Perform Bulk Insertion
                        
                        # 1. Insert Products and get IDs
                        products_tuples = [
                            (
                                r['main']['barcode'], r['main']['product_name'], r['main']['brand_name'], 
                                r['main']['manufacturer'], r['main']['main_category'], r['main']['category_path'],
                                r['main']['serving_size']
                            )
                            for r in batch_buffer
                        ]
                        
                        with conn.cursor() as cur:
                            ids = execute_values(
                                cur, 
                                insert_product_sql, 
                                products_tuples, 
                                fetch=True
                            )
                            
                            countries_tuples = []
                            sources_tuples = []
                            
                            for i, (new_id,) in enumerate(ids):
                                record = batch_buffer[i]
                                
                                for c_tag in record['countries']:
                                    if c_tag.lower() in country_tags:
                                        countries_tuples.append((new_id, c_tag))
                                    
                                for src in record['sources']:
                                    src_url = src.get('url', '')
                                    src_id = src.get('id', '')
                                    import_t = src.get('import_t', 0)
                                    sources_tuples.append((new_id, src_url, src_id, import_t))
                            
                            if countries_tuples:
                                execute_values(cur, insert_countries_sql, countries_tuples)
                            if sources_tuples:
                                execute_values(cur, insert_sources_sql, sources_tuples)
                                
                        conn.commit()
                        batch_buffer = []

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"Error on line {scanned_count}: {e}")
                    conn.rollback()
                    batch_buffer = [] 

        # Final Batch
        if batch_buffer:
            products_tuples = [
                (
                    r['main']['barcode'], r['main']['product_name'], r['main']['brand_name'], 
                    r['main']['manufacturer'], r['main']['main_category'], r['main']['category_path'],
                    r['main']['serving_size']
                )
                for r in batch_buffer
            ]
            
            with conn.cursor() as cur:
                 ids = execute_values(
                    cur, 
                    insert_product_sql, 
                    products_tuples, 
                    fetch=True
                )
                 countries_tuples = []
                 sources_tuples = []
                 for i, (new_id,) in enumerate(ids):
                    record = batch_buffer[i]
                    for c_tag in record['countries']:
                        if c_tag.lower() in country_tags:
                            countries_tuples.append((new_id, c_tag))
                    for src in record['sources']:
                        src_url = src.get('url', '')
                        src_id = src.get('id', '')
                        import_t = src.get('import_t', 0)
                        sources_tuples.append((new_id, src_url, src_id, import_t))
                 
                 if countries_tuples:
                    execute_values(cur, insert_countries_sql, countries_tuples)
                 if sources_tuples:
                    execute_values(cur, insert_sources_sql, sources_tuples)
            
            conn.commit()

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        conn.close()
        print(f"Done. Total Scanned: {scanned_count}. Total Imported: {imported_count}.")

if __name__ == "__main__":
    main()
