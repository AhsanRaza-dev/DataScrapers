from main import get_db_connection
from psycopg2.extras import RealDictCursor
import sys

print("Checking devices table schema and data...")

try:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check columns
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'devices'")
    columns = [row['column_name'] for row in cursor.fetchall()]
    print(f"Columns in devices: {columns}")
    
    if 'picture' in columns:
        cursor.execute("SELECT id, name, picture FROM devices LIMIT 5")
        rows = cursor.fetchall()
        for row in rows:
            print(f"ID: {row['id']}, Name: {row['name']}, Picture: {row['picture']}")
    else:
        print("'picture' column not found!")

    conn.close()

except Exception as e:
    print(f"Error: {e}")
