import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import traceback
import argparse
import time
from dotenv import load_dotenv

# Load Postgres credentials
load_dotenv(r'd:\curiologix\barcode\.env')

# Configuration
SERVICE_ACCOUNT_KEY = r'd:\curiologix\barcode\serviceAccountKey.json'
COLLECTION_NAME = 'products'
BATCH_SIZE = 500  # Firestore batch limit

# DB Config
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

def get_pg_connection():
    # 0. Try direct connection if DB_NAME is set
    if DB_NAME:
        print(f"Attempting to connect to configured DB: {DB_NAME}")
        try:
            conn = psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT
            )
            print(f"Connected to Postgres DB: {DB_NAME}")
            return conn
        except Exception as e:
            print(f"Direct connection to {DB_NAME} failed: {e}. Falling back to discovery.")
    
    # 1. First connect to default postgres to find the real DB name
    target_db_prefix = "country-vise" 
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
        # Fallback to hardcoded if discovery fails
        real_db_name = "food-facts-country-vise"

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
        print(f"Connected to Postgres DB: {real_db_name}")
        return conn
    except Exception as e:
        print(f"Error connecting to database '{real_db_name}': {e}")
        return None

def main():
    if not os.path.exists(SERVICE_ACCOUNT_KEY):
        print(f"ERROR: Service Account Key not found at {SERVICE_ACCOUNT_KEY}")
        print("Please place your Firebase JSON key in this location.")
        return

    print("Connecting to Firebase...")
    try:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firebase initialized.")
    except Exception as e:
        print(f"Firebase Init Error: {e}")
        traceback.print_exc()
        return

    conn = get_pg_connection()
    if not conn:
        print("Could not connect to Postgres.")
        return

    # Parse arguments for resumability
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=0, help='Offset to start migration from')
    args = parser.parse_args()

    LIMIT = 500
    OFFSET = args.start
    total_migrated = OFFSET # Track total including previous runs effectively for display? No, just tracking session.
    
    print(f"Starting migration from offset {OFFSET}...")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            while True:
                print(f"Fetching batch offset {OFFSET}...")
                
                # 1. Fetch Products
                cur.execute(f"""
                    SELECT * FROM products 
                    ORDER BY id 
                    LIMIT {LIMIT} OFFSET {OFFSET}
                """)
                products = cur.fetchall()
                
                if not products:
                    print("No more products found (or empty batch). Migration finished.")
                    break
                
                print(f"Fetched {len(products)} products from DB.")

                product_ids = [p['id'] for p in products]
                products_map = {p['id']: p for p in products}
                
                # Initialize relations arrays
                for pid in products_map:
                    products_map[pid]['countries'] = []
                    products_map[pid]['sources'] = []

                # 2. Fetch Countries for this batch
                if product_ids:
                    placeholders = ','.join(['%s'] * len(product_ids))
                    cur.execute(f"""
                        SELECT product_id, country_tag 
                        FROM product_countries 
                        WHERE product_id IN ({placeholders})
                    """, tuple(product_ids))
                    
                    for row in cur.fetchall():
                        pid = row['product_id']
                        products_map[pid]['countries'].append(row['country_tag'])
                        
                    # 3. Fetch Sources for this batch
                    cur.execute(f"""
                        SELECT product_id, source_url, source_id, import_t 
                        FROM product_sources 
                        WHERE product_id IN ({placeholders})
                    """, tuple(product_ids))
                    
                    for row in cur.fetchall():
                        pid = row['product_id']
                        source_obj = {
                            "url": row['source_url'],
                            "id": row['source_id'],
                            "import_t": row['import_t']
                        }
                        products_map[pid]['sources'].append(source_obj)

                # 4. Prepare Firestore Batch
                print("Preparing Firestore batch...")
                try:
                    batch = db.batch()
                    doc_count = 0
                    
                    for pid, p_data in products_map.items():
                        # Construct Document
                        barcode = p_data['barcode']
                        if not barcode:
                            continue 
                            
                        doc_data = {
                            "product_name": p_data['product_name'],
                            "brand_name": p_data['brand_name'],
                            "manufacturer": p_data['manufacturer'],
                            "main_category": p_data['main_category'],
                            "category_path": p_data['category_path'],
                            "serving_size": p_data['serving_size'],
                            "countries": p_data['countries'],
                            "sources": p_data['sources'],
                            "migrated_at": firestore.SERVER_TIMESTAMP
                        }
                        
                        # Remove keys with None values
                        doc_data = {k: v for k, v in doc_data.items() if v is not None}

                        doc_ref = db.collection(COLLECTION_NAME).document(barcode)
                        batch.set(doc_ref, doc_data)
                        doc_count += 1
                    
                    # 5. Commit Batch
                    if doc_count > 0:
                        print(f"Committing batch of {doc_count}...")
                        batch.commit()
                        total_migrated += doc_count
                        print(f"Committed {doc_count} documents. Session Total: {total_migrated}. Global Offset: {OFFSET + LIMIT}")
                        time.sleep(1.0) # Rate limit protection
                    else:
                         print("Batch empty (no valid barcodes?).")

                except Exception as fire_e:
                    print(f"Firestore Batch Error at offset {OFFSET}:")
                    traceback.print_exc()
                    break

                OFFSET += LIMIT

    except Exception as e:
        print("General Logic Error:")
        traceback.print_exc()
    finally:
        conn.close()
        print(f"Migration Script Ended. Total success: {total_migrated}")

if __name__ == "__main__":
    main()
