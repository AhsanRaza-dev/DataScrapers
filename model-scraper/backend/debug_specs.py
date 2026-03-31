from main import get_db_connection
from psycopg2.extras import RealDictCursor

print("Inspecting memory specifications...")

try:
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get distinct spec keys related to memory/storage
    cursor.execute("""
        SELECT DISTINCT category, spec_key
        FROM device_specifications 
        WHERE (category ILIKE '%Memory%' OR spec_key ILIKE '%Internal%' OR spec_key ILIKE '%Card%')
        ORDER BY category, spec_key
    """)
    keys = cursor.fetchall()
    print("Found relevant keys:")
    for k in keys:
        print(f"{k['category']} - {k['spec_key']}")
        
    print("\nSample values for 'Internal' memory:")
    cursor.execute("""
        SELECT spec_value, COUNT(*) as count
        FROM device_specifications 
        WHERE spec_key = 'Internal'
        GROUP BY spec_value
        ORDER BY count DESC
        LIMIT 20
    """)
    values = cursor.fetchall()
    for v in values:
        print(f"{v['spec_value']} ({v['count']})")

    conn.close()

except Exception as e:
    print(f"Error: {e}")
