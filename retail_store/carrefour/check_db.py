import os
from database import get_session, Product, Brand, Category, SubCategory, ProductVariant

session = get_session()
products = session.query(Product).all()

print(f"Products: {len(products)}")
print(f"Categories: {session.query(Category).count()}")
print(f"SubCategories: {session.query(SubCategory).count()}")
print(f"Brands: {session.query(Brand).count()}")
print(f"Variants: {session.query(ProductVariant).count()}")

for p in products:
    brand_name = p.brand.name if p.brand else "N/A"
    cat_name = p.category.name if p.category else "N/A"
    sub_name = p.subcategory.name if p.subcategory else "N/A"
    variant_details = ", ".join([f"{v.name}: {v.value}" for v in p.variants])
    print(f"\nProduct: {p.name}")
    print(f"Brand: {brand_name}")
    print(f"Category: {cat_name} -> {sub_name}")
    print(f"Variants: {variant_details}")
