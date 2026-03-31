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
OUTPUT_COUNTS_JSON = r'd:\curiologix\barcode\brand_counts.json'
OUTPUT_COUNTS_MD = r'd:\curiologix\barcode\brand_counts.md'

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
    """Create the table if it doesn't exist."""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS mapped_products (
        id SERIAL PRIMARY KEY,
        barcode TEXT,
        brand_name TEXT,
        product_data JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_brand_name ON mapped_products(brand_name);
    """
    with conn.cursor() as cur:
        cur.execute(create_table_query)
    conn.commit()

def load_brands(filepath):
    """Load and normalize brands from the JSON file."""
    if not os.path.exists(filepath):
        print(f"Error: Brand file '{filepath}' not found.")
        return []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if "grocery_brands_pakistan" in data:
            return [b.strip() for b in data["grocery_brands_pakistan"] if b.strip()]
        return []

def main():
    # 1. Load Brands
    brands = load_brands(BRAND_FILE)
    if not brands:
        print("No brands found to map.")
        return

    print(f"Loaded {len(brands)} brands for mapping.")
    
    # 2. Database Setup
    conn = get_db_connection()
    if not conn:
        print("Failed to connect to database. Exiting.")
        return
    
    setup_database(conn)
    print("Database connected and table ready.")

    # 3. Compile Regex
    escaped_brands = [re.escape(b) for b in brands]
    pattern_str = r'\b(' + '|'.join(escaped_brands) + r')\b'
    try:
        brand_pattern = re.compile(pattern_str, re.IGNORECASE)
    except re.error as e:
        print(f"Error compiling regex: {e}")
        conn.close()
        return

    print("Pattern compiled. Scanning file...")

    # 4. Stream and Batch Insert
    matched_count = 0
    scanned_count = 0
    
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file '{INPUT_FILE}' not found.")
        conn.close()
        return
        
    normalized_brands = {b.lower(): b for b in brands}
    brand_counts = {b: 0 for b in brands}
    
    batch_size = 1000
    batch_buffer = []

    # ... (previous code)

    insert_query = """
        INSERT INTO mapped_products (barcode, brand_name, product_data)
        VALUES (%s, %s, %s)
    """

    def save_batch(batch):
        """Try to save a batch. If it fails, rollback and try one by one."""
        if not batch:
            return
            
        try:
            with conn.cursor() as cur:
                execute_batch(cur, insert_query, batch)
            conn.commit()
        except Exception as e:
            print(f"Batch commit failed: {e}. Retrying individual rows...")
            conn.rollback()
            
            for item in batch:
                try:
                    with conn.cursor() as cur:
                        cur.execute(insert_query, item)
                    conn.commit()
                except Exception as single_e:
                    print(f"Failed to insert item {item[0]}: {single_e}")
                    conn.rollback()

    try:
        with gzip.open(INPUT_FILE, 'rt', encoding='utf-8') as f_in:
            for line in f_in:
                scanned_count += 1
                if scanned_count % 50000 == 0:
                    print(f"Scanned {scanned_count} records... Found {matched_count} matches.")

                try:
                    product = json.loads(line)
                    product_brands = product.get('brands', '')
                    
                    if not product_brands:
                        continue
                    
                    matches = brand_pattern.findall(product_brands)
                    
                    if matches:
                        unique_matches = set(m.lower() for m in matches)
                        
                        found_any = False
                        for m in unique_matches:
                            if m in normalized_brands:
                                canonical_name = normalized_brands[m]
                                brand_counts[canonical_name] += 1
                                found_any = True
                                
                                batch_buffer.append((
                                    product.get('code', ''),
                                    canonical_name,
                                    json.dumps(product)
                                ))
                        
                        if found_any:
                            matched_count += 1
                        
                        # Flush batch
                        if len(batch_buffer) >= batch_size:
                            save_batch(batch_buffer)
                            batch_buffer = []

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    print(f"Error processing line {scanned_count}: {e}")
                    # Ensure connection is clean for next iteration
                    if conn.closed == 0: # 0 = 'not closed'
                         conn.rollback()
                    continue

        # flush remaining
        if batch_buffer:
            save_batch(batch_buffer)

    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
    finally:
        if conn:
            conn.close()
        print("Database connection closed.")
    
    # ... (rest of the file)

    print(f"\nProcessing Complete.")
    print(f"Total Scanned: {scanned_count}")
    print(f"Total Matched: {matched_count}")
    
    # Write Counts JSON
    with open(OUTPUT_COUNTS_JSON, 'w', encoding='utf-8') as f:
        sorted_counts = dict(sorted(brand_counts.items(), key=lambda item: item[1], reverse=True))
        json.dump(sorted_counts, f, indent=4)
    print(f"Brand counts (JSON) saved to: {OUTPUT_COUNTS_JSON}")

    # Write Counts Markdown
    with open(OUTPUT_COUNTS_MD, 'w', encoding='utf-8') as f:
        f.write(f"# Brand Product Counts\n\nTotal Matched Products: {matched_count}\n\n")
        f.write("| Brand | Count |\n")
        f.write("|-------|-------|\n")
        sorted_items = sorted(brand_counts.items(), key=lambda item: item[1], reverse=True)
        for brand, count in sorted_items:
            if count > 0:
                f.write(f"| {brand} | {count} |\n")
    print(f"Brand counts (MD) saved to: {OUTPUT_COUNTS_MD}")

if __name__ == "__main__":
    main()
