from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import os
import time
from dotenv import load_dotenv
from contextlib import contextmanager

# Load environment variables
load_dotenv(r'd:\curiologix\barcode\.env')

app = FastAPI()

# Setup Templates
templates = Jinja2Templates(directory="templates")

# DB Config (Supabase)
DB_NAME = os.getenv("SUPABASE_DB_NAME")
DB_USER = os.getenv("SUPABASE_USER")
DB_PASSWORD = os.getenv("SUPABASE_PASSWORD")
DB_HOST = os.getenv("SUPABASE_HOST")
DB_PORT = os.getenv("SUPABASE_PORT")

# Initialize Connection Pool
try:
    db_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=20,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    print("Database connection pool created successfully.")
except Exception as e:
    print(f"Error creating connection pool: {e}")
    db_pool = None

@contextmanager
def get_db_connection():
    if not db_pool:
        raise Exception("Database pool not initialized")
    
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)

@app.on_event("shutdown")
def shutdown_event():
    if db_pool:
        db_pool.closeall()
        print("Database pool closed.")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/suggest")
async def suggest_product(q: str = Query(..., min_length=2)):
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Search by barcode, product name, OR brand name
                query = """
                    SELECT barcode, product_name, brand_name
                    FROM products 
                    WHERE barcode ILIKE %s 
                       OR product_name ILIKE %s 
                       OR brand_name ILIKE %s
                    LIMIT 5
                """
                search_term = f"{q}%"
                name_term = f"%{q}%"
                cur.execute(query, (search_term, name_term, name_term))
                results = cur.fetchall()
                
                suggestions = []
                for r in results:
                    suggestions.append({
                        "value": r['barcode'],
                        "label": f"{r['barcode']} - {r['brand_name'] or ''} {r['product_name'] or 'Unknown'}"
                    })
                return JSONResponse(content=suggestions)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/search")
async def search_product(
    barcode: str = Query(None, description="Barcode to search for"),
    name: str = Query(None, description="Product Name to search for"),
    brand: str = Query(None, description="Brand Name to search for"),
    category: str = Query(None, description="Category to search for")
):
    start_time = time.time()
    
    if not any([barcode, name, brand, category]):
        elapsed_time = (time.time() - start_time) * 1000
        return JSONResponse(
            status_code=400, 
            content={"error": "At least one parameter (barcode, name, brand, category) is required", "execution_time_ms": elapsed_time}
        )

    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Base Query
                base_query = """
                    SELECT 
                        barcode as code,
                        product_name,
                        brand_name as brands,
                        manufacturer,
                        main_category,
                        category_path,
                        serving_size
                    FROM products 
                """
                
                conditions = []
                params = []
                
                if barcode:
                    conditions.append("barcode = %s")
                    params.append(barcode)
                
                if name:
                    if not brand and not category and not barcode:
                         conditions.append("(product_name ILIKE %s OR brand_name ILIKE %s)")
                         params.append(f"%{name}%")
                         params.append(f"%{name}%")
                    else:
                         conditions.append("product_name ILIKE %s")
                         params.append(f"%{name}%")

                if brand:
                    conditions.append("brand_name ILIKE %s")
                    params.append(f"%{brand}%")
                
                if category:
                    conditions.append("(main_category ILIKE %s OR category_path ILIKE %s)")
                    params.append(f"%{category}%")
                    params.append(f"%{category}%")
                
                where_clause = " AND ".join(conditions)
                query = f"{base_query} WHERE {where_clause} LIMIT 1;"
                
                cur.execute(query, tuple(params))
                result = cur.fetchone()
                
                elapsed_time = (time.time() - start_time) * 1000
                
                if result:
                    response_data = dict(result)
                    response_data['execution_time_ms'] = elapsed_time
                    # Handle missing image column gracefully
                    response_data['image_url'] = None 
                    return JSONResponse(content=response_data)
                else:
                    return JSONResponse(
                        status_code=404, 
                        content={
                            "error": "Product not found", 
                            "query": {"barcode": barcode, "name": name, "brand": brand, "category": category},
                            "execution_time_ms": elapsed_time
                        }
                    )
    except Exception as e:
        elapsed_time = (time.time() - start_time) * 1000
        return JSONResponse(status_code=500, content={"error": str(e), "execution_time_ms": elapsed_time})
