from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import psycopg2
import os
import time
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv(r'd:\curiologix\barcode\.env')

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# DB Config
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['GET'])
def search_product():
    start_time = time.time()
    barcode = request.args.get('barcode')
    
    if not barcode:
        return jsonify({"error": "Barcode parameter is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        with conn.cursor() as cur:
            # Try to query the 'mapped_products' table first (legacy/current schema)
            query = "SELECT product_data FROM mapped_products WHERE barcode = %s LIMIT 1;"
            cur.execute(query, (barcode,))
            result = cur.fetchone()
            
            elapsed_time = (time.time() - start_time) * 1000 # Convert to ms
            
            if result:
                # product_data is already a JSONB object, so psycopg2 returns it as a dict
                response_data = result[0]
                # Inject timing info into the response (or wrapper)
                # Since product_data is the raw object, let's wrap it or just add the field if it's a dict
                if isinstance(response_data, dict):
                    response_data['execution_time_ms'] = elapsed_time
                else:
                    # Fallback if it's somehow not a dict
                    response_data = {"data": response_data, "execution_time_ms": elapsed_time}
                    
                return jsonify(response_data)
            else:
                return jsonify({"error": "Product not found", "barcode": barcode, "execution_time_ms": elapsed_time}), 404
                
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
