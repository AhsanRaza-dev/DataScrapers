from models import SessionLocal, Category, Subcategory, Unit, Product, ProductSpecification, Base, engine
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure tables exist just in case they were dropped manually
Base.metadata.create_all(bind=engine)

def get_or_create_category(session, name: str):
    if not name:
        name = "Uncategorized"
    category = session.query(Category).filter_by(name=name).first()
    if not category:
        category = Category(name=name)
        session.add(category)
        session.commit()
    return category

def get_or_create_subcategory(session, name: str, category_id: int):
    subcategory = session.query(Subcategory).filter_by(name=name, category_id=category_id).first()
    if not subcategory:
        subcategory = Subcategory(name=name, category_id=category_id)
        session.add(subcategory)
        session.commit()
    return subcategory

def get_or_create_unit(session, name: str):
    if not name:
        name = "piece"
    unit = session.query(Unit).filter_by(name=name).first()
    if not unit:
        unit = Unit(name=name)
        session.add(unit)
        session.commit()
    return unit

def save_product(session, product_data: dict):
    """
    Expects product_data dict with keys corresponding loosely to fields.
    Supports a 'categories' list for a nested hierarchy (max depth 2 for Category -> Subcategory).
    """
    categories = product_data.get('categories', [])
    category = None
    subcategory = None
    
    if categories:
        cat_name = categories[0].strip() if len(categories) > 0 else "Uncategorized"
        category = get_or_create_category(session, cat_name)
        
        if len(categories) > 1:
            subcat_name = categories[1].strip()
            subcategory = get_or_create_subcategory(session, subcat_name, category.id)
    else:
        category_name = product_data.get('category', '').strip()
        category = get_or_create_category(session, category_name)

    unit_name = product_data.get('unit', 'piece').strip()
    unit = get_or_create_unit(session, unit_name)

    sku = product_data.get('sku')
    
    product = None
    if sku:
        product = session.query(Product).filter_by(sku=sku).first()
        
    if not product:
        product = Product(
            name=product_data.get('name'),
            brand=product_data.get('brand', ''),
            sku=sku,
            barcode=product_data.get('barcode', ''),
            category_id=category.id if category else None,
            subcategory_id=subcategory.id if subcategory else None,
            description=product_data.get('description', ''),
            instructions=product_data.get('instructions', ''),
            stock_quantity=product_data.get('stockQuantity', 0),
            min_stock=product_data.get('minStock', 0),
            unit_id=unit.id,
            is_active=product_data.get('isActive', True),
            has_variants=product_data.get('hasVariants', False)
        )
        session.add(product)
        session.flush() # Ensure product.id is generated for specifications
        logger.info(f"Added new product: {product.name}")
    else:
        # Update existing
        product.name = product_data.get('name')
        product.brand = product_data.get('brand', '')
        product.barcode = product_data.get('barcode', '')
        product.category_id = category.id if category else None
        product.subcategory_id = subcategory.id if subcategory else None
        product.description = product_data.get('description', '')
        product.instructions = product_data.get('instructions', '')
        product.unit_id = unit.id
        logger.info(f"Updated product: {product.name}")
        
    # Process Specifications
    specs = product_data.get('specifications', {})
    if specs:
        # Clear existing specifications for a clean update
        session.query(ProductSpecification).filter_by(product_id=product.id).delete()
        for k, v in specs.items():
            spec = ProductSpecification(product_id=product.id, key=str(k), value=str(v))
            session.add(spec)
            
    session.commit()
    return product
    
if __name__ == "__main__":
    # simple test
    with SessionLocal() as session:
        save_product(session, {
            "name": "Test Product",
            "sku": "TEST12345",
            "categories": ["Meat & Seafood", "Beef", "Steaks"],
            "specifications": {
                "Brand": "TestBrand",
                "Weight": "1.5 kg"
            }
        })
