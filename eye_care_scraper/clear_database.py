import database

conn = database.get_connection()
if conn:
    try:
        cur = conn.cursor()
        
        # Clear all tables and reset IDs
        cur.execute("TRUNCATE TABLE sunglasses RESTART IDENTITY CASCADE")
        
        conn.commit()
        print("Database cleared successfully!")
        print("All products, colors, measurements, and widths have been removed.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error clearing database: {e}")
        conn.rollback()
else:
    print("Failed to connect to database")
