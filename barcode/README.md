# Barcode Intelligence Project

This project maps and searches product data from OpenFoodFacts for specific brands using a high-performance PostgreSQL database.

## `app.py` Explanation

The `app.py` file is the core **Flask Web Server** that powers the search functionality. It acts as the bridge between the user interface and the PostgreSQL database.

### Key Responsibilities

1.  **Web Server & Routing**:
    *   It initializes a Flask application.
    *   **Route `/`**: Serves the user interface (`templates/index.html`).
    *   **Route `/search`**: The API endpoint that accepts a `barcode` parameter, queries the database, and returns product data.

2.  **Database Connection**:
    *   It uses `psycopg2` to establish a secure connection to your PostgreSQL database.
    *   It configures the connection using sensitive credentials loaded from the `.env` file (User: `postgres`, DB: `food-fact`, etc.).

3.  **Search Logic**:
    *   When a request comes in (e.g., `/search?barcode=123`), it executes a refined SQL query:
        ```sql
        SELECT product_data FROM mapped_products WHERE barcode = ... LIMIT 1;
        ```
    *   It extracts the raw JSONB data stored in the database.

4.  **Performance Monitoring**:
    *   It tracks the exact execution time of every search request.
    *   It calculates `elapsed_time` (in milliseconds) and injects this into the API response so the UI can display how fast the database replied.

### How to Run
To start the application:

```bash
# Activate virtual environment
.\venv\Scripts\activate

# Run the server
python app.py
```

The server will start on `http://localhost:5000`.

### Firebase Migration

To transfer data from PostgreSQL to Firebase Firestore:

1.  **Prerequisites**:
    *   Get your `serviceAccountKey.json` from Firebase Console.
    *   Place it in the project root: `d:\curiologix\barcode\serviceAccountKey.json`.

2.  **Run Migration**:
    ```bash
    python migrate_firebase.py
    ```
    This will upload all mapped products to the `products` collection in Firestore.
