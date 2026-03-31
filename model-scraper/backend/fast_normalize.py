import re
from main import get_db_connection
from psycopg2.extras import RealDictCursor, execute_values

def normalize_storage():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        print("Fetching device specifications...")
        cursor.execute("""
            SELECT device_id, spec_value 
            FROM device_specifications 
            WHERE spec_key = 'Internal'
        """)
        rows = cursor.fetchall()
        print(f"Loaded {len(rows)} specifications.")

        storage_regex = re.compile(r'(\d+)\s*(GB|TB)', re.IGNORECASE)
        
        # 1. Collect all unique storage sizes
        unique_options = {} # size_str -> sort_val
        device_mappings = [] # (device_id, size_str)

        for row in rows:
            device_id = row['device_id']
            spec_val = row['spec_value']
            matches = storage_regex.findall(spec_val)
            
            for amount, unit in matches:
                unit = unit.upper()
                size_str = f"{amount}{unit}"
                
                if size_str not in unique_options:
                    sort_val = int(amount)
                    if unit == 'GB':
                        sort_val *= 1024
                    elif unit == 'TB':
                        sort_val *= 1024 * 1024
                    unique_options[size_str] = sort_val
                
                device_mappings.append((device_id, size_str))

        print(f"Found {len(unique_options)} unique storage options.")
        
        # 2. Insert Storage Options
        print("Inserting storage options...")
        # Get existing options first to avoid conflicts/gaps
        cursor.execute("SELECT size, id FROM storage_options")
        existing = {row['size']: row['id'] for row in cursor.fetchall()}
        
        new_options = []
        for size, sort_val in unique_options.items():
            if size not in existing:
                new_options.append((size, sort_val))
        
        if new_options:
            execute_values(
                cursor,
                "INSERT INTO storage_options (size, sort_value) VALUES %s RETURNING id, size",
                new_options
            )
            for row in cursor.fetchall():
                existing[row['size']] = row['id']
            conn.commit()
            print(f"Inserted {len(new_options)} new options.")
        else:
            print("No new options to insert.")

        # 3. Insert Device Storage Links
        print("Preparing device storage links...")
        final_links = []
        unique_links = set() # (device_id, storage_id) to avoid dups

        for device_id, size_str in device_mappings:
            storage_id = existing.get(size_str)
            if storage_id:
                if (device_id, storage_id) not in unique_links:
                    final_links.append((device_id, storage_id))
                    unique_links.add((device_id, storage_id))
        
        print(f"Inserting {len(final_links)} links...")
        
        # Clear existing links to be safe/clean? Or just ON CONFLICT DO NOTHING?
        # Let's do ON CONFLICT to be safe and additive.
        # batch insert
        execute_values(
            cursor,
            "INSERT INTO device_storage (device_id, storage_id) VALUES %s ON CONFLICT DO NOTHING",
            final_links
        )
        
        conn.commit()
        print("Normalization complete!")

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    normalize_storage()
