from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB Connection (Reusing your env var style, but ideally use env vars)
# For now hardcoding strictly based on your provided info, but best practice is env.
# You said: DIRECT_URL="postgresql://postgres.ctvjspnrxtpofjfawnaj:[YOUR-PASSWORD]@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres"

DB_HOST = "aws-1-ap-southeast-1.pooler.supabase.com"
DB_NAME = "postgres"
DB_USER = "postgres.ctvjspnrxtpofjfawnaj"
DB_PASS = "Ah72n):(:$12"
DB_PORT = "5432"

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Error connecting to DB: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

@app.get("/")
def read_root():
    return {"message": "Model Scraper API"}

@app.get("/api/brands")
def get_brands(limit: int = 100):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM brands ORDER BY name LIMIT %s", (limit,))
        brands = cursor.fetchall()
        return brands
    except Exception as e:
        print(f"Error fetching brands: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        cursor.close()
        conn.close()

@app.get("/api/brands/search")
def search_brands(q: str = Query(..., min_length=1)):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM brands WHERE name ILIKE %s LIMIT 10", (f"%{q}%",))
        brands = cursor.fetchall()
        return brands
    finally:
        cursor.close()
        conn.close()

@app.get("/api/brands/{brand_id}/subcategories")
def get_subcategories(brand_id: int):
    # Logic: Group devices by type based on name
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Determine available types dynamically for this brand
        # Optimization: Just check existence of types
        categories = set()
        
        # Check for Watches
        cursor.execute("SELECT 1 FROM devices WHERE brand_id = %s AND (name ILIKE '%%Watch%%' OR name ILIKE '%%Gear%%' OR name ILIKE '%%Band%%') LIMIT 1", (brand_id,))
        if cursor.fetchone():
            categories.add("watches")
            
        # Check for Tablets
        cursor.execute("SELECT 1 FROM devices WHERE brand_id = %s AND (name ILIKE '%%Tab%%' OR name ILIKE '%%Pad%%' OR name ILIKE '%%Slate%%') LIMIT 1", (brand_id,))
        if cursor.fetchone():
            categories.add("tablets")

        # Check for Accessories (Headsets, Earbuds, VR, etc.)
        cursor.execute("SELECT 1 FROM devices WHERE brand_id = %s AND (name ILIKE '%%Headset%%' OR name ILIKE '%%Buds%%' OR name ILIKE '%%AirPods%%' OR name ILIKE '%%VR%%' OR name ILIKE '%%Accessory%%') LIMIT 1", (brand_id,))
        if cursor.fetchone():
            categories.add("accessories")
            
        # Check for Phones (Assumed if devices exist and not just watches/tablets/acc, or just default to have it)
        cursor.execute("SELECT 1 FROM devices WHERE brand_id = %s LIMIT 1", (brand_id,))
        # Simple heuristic: If we have devices that are NOT the above, show phones. 
        # But for UI simplicity, let's almost always show phones if the brand has items.
        # Ideally we check: count(all) > count(watches+tablets+acc)
        categories.add("phones")

        return [{"id": cat, "name": cat.capitalize()} for cat in categories]
    finally:
        cursor.close()
        conn.close()

@app.get("/api/devices")
def get_devices(brand_id: int, type: str = "phones", storage: str = Query(None)):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = """
            SELECT d.* 
            FROM devices d
            WHERE d.brand_id = %s
        """
        params = [brand_id]
        
        # Type Filtering
        if type == "watches":
            query += " AND (d.name ILIKE '%%Watch%%' OR d.name ILIKE '%%Gear%%' OR d.name ILIKE '%%Band%%')"
        elif type == "tablets":
            query += " AND (d.name ILIKE '%%Tab%%' OR d.name ILIKE '%%Pad%%' OR d.name ILIKE '%%Slate%%')"
        elif type == "accessories":
            query += " AND (d.name ILIKE '%%Headset%%' OR d.name ILIKE '%%Buds%%' OR d.name ILIKE '%%AirPods%%' OR d.name ILIKE '%%VR%%' OR d.name ILIKE '%%Accessory%%')"
        else: # phones
            query += " AND NOT (d.name ILIKE '%%Watch%%' OR d.name ILIKE '%%Gear%%' OR d.name ILIKE '%%Band%%') AND NOT (d.name ILIKE '%%Tab%%' OR d.name ILIKE '%%Pad%%' OR d.name ILIKE '%%Slate%%') AND NOT (d.name ILIKE '%%Headset%%' OR d.name ILIKE '%%Buds%%' OR d.name ILIKE '%%AirPods%%' OR d.name ILIKE '%%VR%%' OR d.name ILIKE '%%Accessory%%')"

        # Storage Filtering
        if storage:
            # Join with device_storage table
            query += """
                AND EXISTS (
                    SELECT 1 
                    FROM device_storage ds
                    JOIN storage_options so ON ds.storage_id = so.id
                    WHERE ds.device_id = d.id 
                    AND so.size = %s
                )
            """
            params.append(storage)

        cursor.execute(query, tuple(params))
        devices = cursor.fetchall()
        return devices
    finally:
        cursor.close()
        conn.close()

@app.get("/api/filters/storage")
def get_storage_options():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT size FROM storage_options ORDER BY sort_value")
        options = cursor.fetchall()
        return [opt['size'] for opt in options]
    finally:
        cursor.close()
        conn.close()

@app.get("/api/devices/{device_id}")
def get_device_details(device_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get Device Info
        cursor.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
        device = cursor.fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
            
        # Get Specs
        cursor.execute("SELECT category, spec_key, spec_value FROM device_specifications WHERE device_id = %s ORDER BY id", (device_id,))
        specs_rows = cursor.fetchall()
        
        # Group Specs
        specifications = {}
        for row in specs_rows:
            cat = row['category'] or "General"
            if cat not in specifications:
                specifications[cat] = []
            specifications[cat].append({"key": row['spec_key'], "value": row['spec_value']})
            
        return {**device, "specifications": specifications}
    finally:
        cursor.close()
        conn.close()
