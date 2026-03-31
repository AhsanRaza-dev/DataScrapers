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
    
    print("Columns in 'products':")
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'products'
    """)
    for row in cur.fetchall():
        print(f"- {row[0]}")

    conn.close()
except Exception as e:
    print(f"Error: {e}")
