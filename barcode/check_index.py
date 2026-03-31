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
    cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'products'")
    indexes = cur.fetchall()
    print("Indexes on 'products':")
    for idx in indexes:
        print(f"- {idx[0]}: {idx[1]}")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
