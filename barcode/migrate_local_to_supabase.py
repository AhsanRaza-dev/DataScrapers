import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import os
import traceback
from dotenv import load_dotenv

# Load credentials
load_dotenv(r'd:\curiologix\barcode\.env')

# Source (Local) Config
SRC_DB_NAME = os.getenv("DB_NAME")
SRC_USER = os.getenv("DB_USER")
SRC_PASSWORD = os.getenv("DB_PASSWORD")
SRC_HOST = os.getenv("DB_HOST")
SRC_PORT = os.getenv("DB_PORT")

# Destination (Supabase) Config
DEST_DB_NAME = os.getenv("SUPABASE_DB_NAME")
DEST_USER = os.getenv("SUPABASE_USER")
DEST_PASSWORD = os.getenv("SUPABASE_PASSWORD")
DEST_HOST = os.getenv("SUPABASE_HOST")
DEST_PORT = os.getenv("SUPABASE_PORT")

def get_connection(name, dbname, user, password, host, port):
    try:
        print(f"Connecting to {name} DB ({host})...")
        conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port
        )
        return conn
    except Exception as e:
        print(f"Error connecting to {name} DB: {e}")
        return None

def create_tables_if_not_exist(dest_conn):
    print("Verifying/Creating tables in Supabase...")
    commands = [
        """
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            barcode VARCHAR(255) UNIQUE,
            product_name TEXT,
            brand_name TEXT,
            manufacturer TEXT,
            main_category TEXT,
            category_path TEXT,
            serving_size TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_countries (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            country_tag VARCHAR(100)
        )
        """,
        """
        DROP TABLE IF EXISTS product_sources CASCADE;
        CREATE TABLE IF NOT EXISTS product_sources (
            id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            source_url TEXT,
            source_id VARCHAR(255),
            import_t BIGINT
        )
        """
    ]
    try:
        with dest_conn.cursor() as cur:
            for cmd in commands:
                cur.execute(cmd)
        dest_conn.commit()
        print("Tables verified.")
    except Exception as e:
        print(f"Error creating tables: {e}")
        dest_conn.rollback()
        raise e

def migrate_data():
    src_conn = get_connection("Source", SRC_DB_NAME, SRC_USER, SRC_PASSWORD, SRC_HOST, SRC_PORT)
    dest_conn = get_connection("Destination", DEST_DB_NAME, DEST_USER, DEST_PASSWORD, DEST_HOST, DEST_PORT)

    if not src_conn or not dest_conn:
        return

    try:
        # 1. Schema Migration
        create_tables_if_not_exist(dest_conn)

        # 2. Data Migration
        batch_size = 1000
        offset = 0
        
        while True:
            print(f"Fetching products batch offset {offset}...")
            with src_conn.cursor(cursor_factory=RealDictCursor) as src_cur:
                 # Fetch full product rows
                src_cur.execute(f"SELECT * FROM products ORDER BY id LIMIT {batch_size} OFFSET {offset}")
                products = src_cur.fetchall()
                
                if not products:
                    print("No more products. Migration finished.")
                    break

                # Prepare insert data
                product_values = []
                for p in products:
                    # Map src columns to dest columns explicit order
                    product_values.append((
                        p['id'], p['barcode'], p['product_name'], p['brand_name'], 
                        p['manufacturer'], p['main_category'], p.get('category_path'), p.get('serving_size')
                    ))
                
                # Insert Products (Upsert)
                print(f"Inserting {len(products)} products into Supabase...")
                with dest_conn.cursor() as dest_cur:
                    insert_query = """
                        INSERT INTO products (id, barcode, product_name, brand_name, manufacturer, main_category, category_path, serving_size)
                        VALUES %s
                        ON CONFLICT (id) DO NOTHING
                    """
                    execute_values(dest_cur, insert_query, product_values, template="(%s, %s, %s, %s, %s, %s, %s, %s)")
                
                # Fetch and Insert Relations (Countries & Sources)
                p_ids = [p['id'] for p in products]
                placeholders = ','.join(['%s'] * len(p_ids))
                
                # Countries
                if p_ids:
                     with src_conn.cursor(cursor_factory=RealDictCursor) as src_cur:
                        src_cur.execute(f"SELECT product_id, country_tag FROM product_countries WHERE product_id IN ({placeholders})", tuple(p_ids))
                        countries = src_cur.fetchall()
                        
                        if countries:
                            country_values = [(c['product_id'], c['country_tag']) for c in countries]
                            with dest_conn.cursor() as dest_cur:
                                execute_values(dest_cur, 
                                    "INSERT INTO product_countries (product_id, country_tag) VALUES %s ON CONFLICT DO NOTHING", 
                                    country_values,
                                    template="(%s, %s)")

                # Sources
                if p_ids:
                     with src_conn.cursor(cursor_factory=RealDictCursor) as src_cur:
                        src_cur.execute(f"SELECT product_id, source_url, source_id, import_t FROM product_sources WHERE product_id IN ({placeholders})", tuple(p_ids))
                        sources = src_cur.fetchall()
                        
                        if sources:
                            source_values = [(s['product_id'], s['source_url'], s['source_id'], s['import_t']) for s in sources]
                            with dest_conn.cursor() as dest_cur:
                                execute_values(dest_cur, 
                                    "INSERT INTO product_sources (product_id, source_url, source_id, import_t) VALUES %s ON CONFLICT DO NOTHING", 
                                    source_values,
                                    template="(%s, %s, %s, %s)")

                dest_conn.commit()
                print(f"Batch committed. Offset {offset}")
                offset += batch_size

    except Exception as e:
        import traceback
        with open('error.log', 'w') as f:
            f.write(str(e))
            f.write('\n')
            traceback.print_exc(file=f)
        print("Error logged to error.log")
    finally:
        if src_conn: src_conn.close()
        if dest_conn: dest_conn.close()

if __name__ == "__main__":
    migrate_data()
