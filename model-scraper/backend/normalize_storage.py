import re
from main import get_db_connection
from psycopg2.extras import RealDictCursor

def normalize_storage():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        print("Creating new tables...")
        # Create storage_options table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS storage_options (
                id SERIAL PRIMARY KEY,
                size VARCHAR(50) UNIQUE NOT NULL,
                sort_value INT NOT NULL
            );
        """)

        # Create device_storage table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_storage (
                device_id INT NOT NULL,
                storage_id INT NOT NULL,
                PRIMARY KEY (device_id, storage_id),
                FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
                FOREIGN KEY (storage_id) REFERENCES storage_options(id) ON DELETE CASCADE
            );
        """)
        conn.commit()

        print("Fetching device specifications...")
        cursor.execute("""
            SELECT device_id, spec_value 
            FROM device_specifications 
            WHERE spec_key = 'Internal'
        """)
        rows = cursor.fetchall()
        
        storage_map = {} # size_str -> id
        
        # Regex to find storage sizes (e.g. 64GB, 128 GB, 1TB)
        # Matches number followed strictly by GB or TB, ignoring case
        storage_regex = re.compile(r'(\d+)\s*(GB|TB)', re.IGNORECASE)

        print(f"Processing {len(rows)} rows...")
        
        for row in rows:
            device_id = row['device_id']
            spec_val = row['spec_value']
            
            matches = storage_regex.findall(spec_val)
            
            for amount, unit in matches:
                # Normalize string: "128GB"
                unit = unit.upper()
                size_str = f"{amount}{unit}"
                
                # Calculate sort value (MB)
                sort_val = int(amount)
                if unit == 'GB':
                    sort_val *= 1024
                elif unit == 'TB':
                    sort_val *= 1024 * 1024
                
                # Insert functionality into storage_options if not exists
                if size_str not in storage_map:
                    # Check DB first
                    cursor.execute("SELECT id FROM storage_options WHERE size = %s", (size_str,))
                    res = cursor.fetchone()
                    if res:
                        storage_map[size_str] = res['id']
                    else:
                        cursor.execute(
                            "INSERT INTO storage_options (size, sort_value) VALUES (%s, %s) RETURNING id",
                            (size_str, sort_val)
                        )
                        storage_map[size_str] = cursor.fetchone()['id']
                        conn.commit() # Commit new option immediately
                
                storage_id = storage_map[size_str]
                
                # Link device to storage
                cursor.execute("""
                    INSERT INTO device_storage (device_id, storage_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (device_id, storage_id))
        
        conn.commit()
        print("Normalization complete!")
        
        # Verify
        cursor.execute("SELECT * FROM storage_options ORDER BY sort_value")
        options = cursor.fetchall()
        print("\nFound storage options:")
        for opt in options:
            print(f"- {opt['size']}")

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    normalize_storage()
