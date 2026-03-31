import psycopg2
import os
from dotenv import load_dotenv

load_dotenv(r'd:\curiologix\barcode\.env')

try:
    conn = psycopg2.connect(
        dbname=os.getenv("SUPABASE_DB_NAME"),
        user=os.getenv("SUPABASE_USER"),
        password=os.getenv("SUPABASE_PASSWORD"),
        host=os.getenv("SUPABASE_HOST"),
        port=os.getenv("SUPABASE_PORT")
    )
    cur = conn.cursor()
    cur.execute("SELECT barcode, product_name FROM products LIMIT 5")
    rows = cur.fetchall()
    print("Sample Products:")
    for r in rows:
        print(f"- {r[0]}: {r[1]}")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
