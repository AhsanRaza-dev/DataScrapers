import os
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Category(Base):
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)

    subcategories = relationship("Subcategory", back_populates="category", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="category")


class Subcategory(Base):
    __tablename__ = 'subcategories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)

    category = relationship("Category", back_populates="subcategories")
    products = relationship("Product", back_populates="subcategory")


class ProductSpecification(Base):
    __tablename__ = 'product_specifications'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    key = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    
    product = relationship("Product", back_populates="specifications")


class Unit(Base):
    __tablename__ = 'units'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)

    products = relationship("Product", back_populates="unit")


class Product(Base):
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    sku = Column(String, unique=True, nullable=True)
    barcode = Column(String, nullable=True)
    
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=True)
    category = relationship("Category", back_populates="products")
    
    subcategory_id = Column(Integer, ForeignKey('subcategories.id'), nullable=True)
    subcategory = relationship("Subcategory", back_populates="products")
    
    brand = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)
    
    stock_quantity = Column(Integer, default=0)
    min_stock = Column(Integer, default=0)
    
    unit_id = Column(Integer, ForeignKey('units.id'), nullable=True)
    unit = relationship("Unit", back_populates="products")
    
    is_active = Column(Boolean, default=True)
    has_variants = Column(Boolean, default=False)
    
    specifications = relationship("ProductSpecification", back_populates="product", cascade="all, delete-orphan")


def init_db():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
    print("Database tables initialized successfully.")
