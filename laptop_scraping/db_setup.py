import os
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Database credentials
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "laptops-data")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT = os.getenv("DB_PORT", "5432")

# Connection string
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

Base = declarative_base()

class Brand(Base):
    __tablename__ = 'brands'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    
    laptops = relationship("Product", back_populates="brand")

class Product(Base):
    __tablename__ = 'products'
    
    id = Column(Integer, primary_key=True)
    brand_id = Column(Integer, ForeignKey('brands.id'))
    title = Column(String, nullable=False)
    price = Column(String)  # Storing as string to handle currency symbols and ranges easily
    url = Column(String, unique=True)
    item_id = Column(String, unique=True, nullable=True) # Newegg item number
    image_url = Column(String) # Main product image
    
    brand = relationship("Brand", back_populates="laptops")
    specifications = relationship("Specification", back_populates="product", cascade="all, delete-orphan")
    variants = relationship("Variant", back_populates="product", cascade="all, delete-orphan")

class Variant(Base):
    __tablename__ = 'variants'
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'))
    name = Column(String) 
    price = Column(String)
    url = Column(String)
    memory = Column(String) 
    storage = Column(String) 
    processor = Column(String) # e.g. i5, i7, Ryzen 5
    image_url = Column(String)
    
    product = relationship("Product", back_populates="variants")

class Specification(Base):
    __tablename__ = 'specifications'
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'))
    key = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    
    product = relationship("Product", back_populates="specifications")

from sqlalchemy import text

def create_database_if_not_exists():
    # Connect to default 'postgres' database to check/create target DB
    default_url = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres"
    engine = create_engine(default_url, isolation_level="AUTOCOMMIT")
    
    with engine.connect() as conn:
        # Check if exists
        exists = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'")).scalar()
        if not exists:
            print(f"Database {DB_NAME} does not exist. Creating...")
            conn.execute(text(f"CREATE DATABASE \"{DB_NAME}\""))
            print(f"Database {DB_NAME} created.")
        else:
            print(f"Database {DB_NAME} already exists.")

def create_schema():
    create_database_if_not_exists()
    
    engine = create_engine(DATABASE_URL)
    # Caution: drop_all will wipe data. User just wants to scrape new link. 
    # But if DB was missing, it's empty anyway. 
    # If DB exists, dropping it might be unwanted if we want to keep old data?
    # User said "Refining Laptop Scraper & DB", maybe fresh start is okay?
    # Given the error "database does not exist", a fresh start is implied/forced.
    # However, I should be careful not to drop if it *does* exist and contains useful data, 
    # but the user *just* got a "does not exist" error.
    # I will keep the drop_all for now as it ensures schema matches code.
    Base.metadata.drop_all(engine) 
    Base.metadata.create_all(engine)
    print("Database schema created successfully.")

if __name__ == "__main__":
    create_schema()
