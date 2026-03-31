import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Ahsan12345@localhost:5432/carrefour_db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    
    subcategories = relationship("SubCategory", back_populates="category")
    products = relationship("Product", back_populates="category")

class SubCategory(Base):
    __tablename__ = "subcategories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    
    category = relationship("Category", back_populates="subcategories")
    products = relationship("Product", back_populates="subcategory")

class Brand(Base):
    __tablename__ = "brands"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    
    products = relationship("Product", back_populates="brand")

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    selling_price = Column(Float, nullable=False)
    sku = Column(String(100), unique=True, index=True)
    barcode = Column(String(100), index=True)
    description = Column(Text)
    buying_price = Column(Float, default=0.0)
    stock_quantity = Column(Integer, default=0)
    min_stock = Column(Integer, default=0)
    unit = Column(String(50), default="piece")
    is_active = Column(Boolean, default=True)
    has_variants = Column(Boolean, default=False)
    
    category_id = Column(Integer, ForeignKey("categories.id"))
    subcategory_id = Column(Integer, ForeignKey("subcategories.id"))
    brand_id = Column(Integer, ForeignKey("brands.id"))
    
    # Extra Fields requested by User
    storage_conditions = Column(Text)
    allergy_advice = Column(Text)
    brand_marketing_message = Column(Text)
    
    # Internal scraper fields
    url = Column(Text, unique=True)
    
    category = relationship("Category", back_populates="products")
    subcategory = relationship("SubCategory", back_populates="products")
    brand = relationship("Brand", back_populates="products")
    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")

class ProductVariant(Base):
    __tablename__ = "product_variants"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    name = Column(String(100), nullable=False)  # e.g., "Flavor", "Capacity"
    value = Column(String(255), nullable=False) # e.g., "Strawberry", "1L"
    
    product = relationship("Product", back_populates="variants")

def init_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def get_session():
    return SessionLocal()

def get_or_create(session, model, defaults=None, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    else:
        params = dict((k, v) for k, v in kwargs.items())
        params.update(defaults or {})
        instance = model(**params)
        session.add(instance)
        # We flush so the instance gets an ID before being attached to products
        session.flush()
        return instance

def save_product(session, data: dict):
    cat_name = data.pop("category", None)
    subcat_name = data.pop("subcategory", None)
    brand_name = data.pop("brand", None)
    variants_data = data.pop("variants", [])
    
    if variants_data:
        data["has_variants"] = True
        
    product = Product(**data)
    
    if cat_name:
        category = get_or_create(session, Category, name=cat_name)
        product.category = category
        
        if subcat_name:
            subcat = get_or_create(session, SubCategory, name=subcat_name, category_id=category.id)
            product.subcategory = subcat
            
    if brand_name:
        brand = get_or_create(session, Brand, name=brand_name)
        product.brand = brand
        
    session.add(product)
    
    for v in variants_data:
        variant = ProductVariant(product=product, name=v["name"], value=v["value"])
        session.add(variant)
        
    session.commit()
    return product
