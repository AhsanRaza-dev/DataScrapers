from main import get_db_connection
from psycopg2.extras import RealDictCursor
import traceback

print("Inspecting device images...")

try:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get a few devices that should have images
        cursor.execute("SELECT id, name, picture FROM devices LIMIT 5")
        devices = cursor.fetchall()
        print(f"Fetched {len(devices)} devices.")
        for d in devices:
            print(f"ID: {d['id']}, Name: {d['name']}")
            print(f"Picture URL: '{d['picture']}'")
            print("-" * 20)

    except Exception as e:
         print("Query failed")
         traceback.print_exc()

    finally:
        cursor.close()
        conn.close()

except Exception as e:
    print(f"Error: {e}")
