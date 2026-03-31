
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def init_db():
    conn = get_connection()
    if not conn:
        print("Failed to connect to DB for initialization.")
        return

    # Schema definition
    commands = [
        """
        CREATE TABLE IF NOT EXISTS sunglasses (
            id SERIAL PRIMARY KEY,
            url TEXT UNIQUE NOT NULL,
            name TEXT,
            price TEXT,
            image_url TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sunglasses_measurements (
            id SERIAL PRIMARY KEY,
            sunglasses_id INTEGER REFERENCES sunglasses(id) ON DELETE CASCADE,
            lens_width TEXT,
            bridge_width TEXT,
            temple_length TEXT,
            UNIQUE(sunglasses_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sunglasses_colors (
            id SERIAL PRIMARY KEY,
            sunglasses_id INTEGER REFERENCES sunglasses(id) ON DELETE CASCADE,
            color_name TEXT,
            price TEXT,
            UNIQUE(sunglasses_id, color_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sunglasses_widths (
            id SERIAL PRIMARY KEY,
            sunglasses_id INTEGER REFERENCES sunglasses(id) ON DELETE CASCADE,
            width_name TEXT,
            frame_width TEXT,
            UNIQUE(sunglasses_id, width_name)
        )
        """
    ]
    
    try:
        cur = conn.cursor()
        for command in commands:
            cur.execute(command)
        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized. Tables: sunglasses, sunglasses_measurements, sunglasses_colors, sunglasses_widths.")
    except Exception as e:
        print(f"Error initializing database: {e}")

def product_exists(url):
    conn = get_connection()
    if not conn:
        return False
    
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sunglasses WHERE url = %s", (url,))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return exists
    except Exception as e:
        print(f"Error checking product existence: {e}")
        return False

def save_product(data):
    conn = get_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        
        # 1. Insert/Update Sunglasses
        upsert_sunglasses = """
        INSERT INTO sunglasses (url, name, price, image_url, scraped_at)
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (url) DO UPDATE SET
            name = EXCLUDED.name,
            price = EXCLUDED.price,
            image_url = EXCLUDED.image_url,
            scraped_at = EXCLUDED.scraped_at
        RETURNING id;
        """
        
        cur.execute(upsert_sunglasses, (
            data.get("url"),
            data.get("name"),
            data.get("price"),
            data.get("image_url")
        ))
        sunglasses_id = cur.fetchone()[0]

        # 2. Insert/Update Measurements
        upsert_measurements = """
        INSERT INTO sunglasses_measurements (sunglasses_id, lens_width, bridge_width, temple_length)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (sunglasses_id) DO UPDATE SET
            lens_width = EXCLUDED.lens_width,
            bridge_width = EXCLUDED.bridge_width,
            temple_length = EXCLUDED.temple_length;
        """
        
        measurements = data.get("measurements", {})
        cur.execute(upsert_measurements, (
            sunglasses_id,
            measurements.get("Lens width"),
            measurements.get("Bridge"),
            measurements.get("Temple length")
        ))

        # 3. Insert Colors
        cur.execute("DELETE FROM sunglasses_colors WHERE sunglasses_id = %s", (sunglasses_id,))
        colors = data.get("colors", [])
        if colors:
            color_values = [(sunglasses_id, c.get("name"), c.get("price")) for c in colors]
            insert_colors = "INSERT INTO sunglasses_colors (sunglasses_id, color_name, price) VALUES (%s, %s, %s)"
            cur.executemany(insert_colors, color_values)

        # 4. Insert Widths
        cur.execute("DELETE FROM sunglasses_widths WHERE sunglasses_id = %s", (sunglasses_id,))
        widths = data.get("width_options", [])
        frame_width_val = measurements.get("Frame Width")
        if widths:
            # We apply the single scraped frame_width to all width options for now as we don't distinguish them yet.
            width_values = [(sunglasses_id, w, frame_width_val) for w in widths]
            insert_widths = "INSERT INTO sunglasses_widths (sunglasses_id, width_name, frame_width) VALUES (%s, %s, %s)"
            cur.executemany(insert_widths, width_values)

        conn.commit()
        cur.close()
        conn.close()
        print(f"Saved/Updated product '{data.get('name')}' (ID: {sunglasses_id}) with image, measurements, colors, and widths.")
        
    except Exception as e:
        print(f"Error saving product {data.get('url')}: {e}")
        if conn:
            conn.rollback()
            conn.close()

if __name__ == "__main__":
    init_db()
