import psycopg2
import os
from dotenv import load_dotenv

load_dotenv(r'd:\curiologix\barcode\.env')

def check():
    try:
        print(f"Connecting to {os.getenv('SUPABASE_HOST')}...")
        conn = psycopg2.connect(
            dbname=os.getenv("SUPABASE_DB_NAME"),
            user=os.getenv("SUPABASE_USER"),
            password=os.getenv("SUPABASE_PASSWORD"),
            host=os.getenv("SUPABASE_HOST"),
            port=os.getenv("SUPABASE_PORT")
        )
        cur = conn.cursor()
        
        # Check tables
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        tables = cur.fetchall()
        print(f"Tables found: {[t[0] for t in tables]}")
        
        # Check product count
        if 'products' in [t[0] for t in tables]:
            cur.execute("SELECT count(*) FROM products")
            count = cur.fetchone()[0]
            print(f"Rows in 'products': {count}")

        # Check product_sources schema
        if 'product_sources' in [t[0] for t in tables]:
             cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'product_sources'")
             cols = cur.fetchall()
             print("Schema 'product_sources':")
             for c in cols:
                 print(f" - {c[0]}: {c[1]}")
             
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check()
