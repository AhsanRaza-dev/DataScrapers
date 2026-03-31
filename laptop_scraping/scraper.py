import os 
import time
import re
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db_setup import Base, Brand, Product, Specification, Variant
from dotenv import load_dotenv

load_dotenv()

# Database setup
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "laptops-data")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_PORT = os.getenv("DB_PORT", "5432")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)
# Ensure tables exist
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

TARGET_URL = "https://www.newegg.com/p/pl?N=100006740%2050001186&d=lenovo+laptops&page=1&isdeptsrh=1"

def navigate_with_retry(page, url, retries=3):
    for i in range(retries):
        try:
            print(f"Navigating to: {url} (Attempt {i+1}/{retries})")
            page.goto(url, timeout=60000)
            return True
        except Exception as e:
            print(f"Navigation failed: {e}")
            if i < retries - 1:
                print("Retrying in 5 seconds...")
                time.sleep(5)
            else:
                print("Max retries reached.")
                raise e

def scrape_newegg():
    print("Please enter the Newegg URL to scrape (e.g., https://www.newegg.com/p/pl?d=mouse&PageSize=96)")
    user_url = input("URL: ").strip()
    
    if not user_url:
        print("No URL provided. Exiting.")
        return

    # Ensure PageSize is set for efficiency if not present
    if "PageSize=" not in user_url:
        if "?" in user_url:
            user_url += "&PageSize=96"
        else:
            user_url += "?PageSize=96"

    print(f"Targeting URL: {user_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        # Initialize detail page once to avoid opening/closing tabs repeatedly
        detail_page = context.new_page()
        
        # Initial navigation
        base_url = user_url
        url = f"{base_url}&page=1"
        try:
            navigate_with_retry(page, url)
        except Exception as e:
            print(f"Fatal error starting scraper: {e}")
            return
        
        # ... CAPTCHA detection remains ...
        # Check for CAPTCHA
        if page.title() == "Are you a human?" or page.is_visible("text='Are you a human?'"):
            print("\n" + "="*50)
            print("CAPTCHA DETECTED! Please manually solve the CAPTCHA in the browser window.")
            print("The script will wait until products are visible.")
            print("="*50 + "\n")
            
            try:
                page.wait_for_selector(".item-cell", timeout=300000)
                print("CAPTCHA solved! Resuming...")
            except:
                print("Timed out waiting for CAPTCHA solution.")
                browser.close()
                return

        current_page_num = 1
        has_next_page = True

        while has_next_page:
            if current_page_num > 1:
                url = f"{base_url}&page={current_page_num}"
                navigate_with_retry(page, url)
                
                if page.title() == "Are you a human?" or page.is_visible("text='Are you a human?'"):
                     print("CAPTCHA on pagination. Please solve.")
                     page.wait_for_selector(".item-cell", timeout=300000)
            
            try:
                if page.is_visible("button.close"):
                    page.click("button.close")
            except:
                pass

            product_cells = page.locator(".item-cell").all()
            print(f"Found {len(product_cells)} products on page {current_page_num}")

            if len(product_cells) == 0:
                print("No products found, stopping.")
                break

            for cell in product_cells:
                try:
                    title_el = cell.locator(".item-title")
                    if not title_el.count():
                        continue
                        
                    title = title_el.first.inner_text()
                    product_url = title_el.first.get_attribute("href")
                    
                    if not product_url: continue

                    price = "N/A"
                    price_current = cell.locator(".price-current")
                    if price_current.count():
                        price = price_current.first.inner_text().replace("\n", "").strip()

                    # Image from list (Fallback)
                    list_img_url = None
                    list_img_el = cell.locator(".item-img img")
                    if list_img_el.count():
                        list_img_url = list_img_el.first.get_attribute("src")

                    if list_img_el.count():
                        list_img_url = list_img_el.first.get_attribute("src")

                    # --- CHECK EXISTENCE BEFORE SCRAPING ---
                    # Extract ID from URL if possible
                    pre_item_id = None
                    pre_match = re.search(r'/p/([^?&/]+)', product_url)
                    if pre_match:
                        pre_item_id = pre_match.group(1)
                    
                    found_existing = False
                    if pre_item_id:
                        found_existing = session.query(Product).filter_by(item_id=pre_item_id).first()
                    
                    if not found_existing:
                        found_existing = session.query(Product).filter_by(url=product_url).first()
                        
                    if found_existing:
                        print(f"Skipping existing item: {title[:30]}...")
                        continue

                    # Visit Product Page for details
                    print(f"Scraping details for: {title[:30]}")
                    
                    # details page is already open, just navigate
                    # detail_page = context.new_page()
                    try:
                        detail_page.goto(product_url, timeout=60000)
                        
                        # --- 1. Scrape Specs ---
                        specs_dict = {}
                        
                        # Try to find and click "Specs" tab (same as before)
                        try:
                            specs_tab = detail_page.locator("div.tab-nav").get_by_text("Specs")
                            if specs_tab.count() and specs_tab.is_visible():
                                specs_tab.click()
                                time.sleep(1) 
                        except:
                            pass
                            
                        # Try Table extraction
                        tables = detail_page.locator("#Specs table").all()
                        if not tables:
                            tables = detail_page.locator("table.table-horizontal").all()
                            
                        for table in tables:
                            rows = table.locator("tr").all()
                            for row in rows:
                                th = row.locator("th")
                                td = row.locator("td")
                                if th.count() and td.count():
                                    k = th.first.inner_text().strip()
                                    v = td.first.inner_text().strip()
                                    specs_dict[k] = v
                                    
                        # Fallback DL/DT/DD
                        if not specs_dict:
                            dls = detail_page.locator("#Specs fieldset dl").all()
                            for dl in dls:
                                dt = dl.locator("dt")
                                dd = dl.locator("dd")
                                if dt.count() and dd.count():
                                    k = dt.first.inner_text().strip()
                                    v = dd.first.inner_text().strip()
                                    specs_dict[k] = v

                        # Fallback: General Property extraction if specific structure fails
                        if not specs_dict:
                            pass

                        # --- Extract Main Image ---
                        main_image_url = None
                        try:
                            # Try high-res original image (same logic)
                            img_el = detail_page.locator(".product-view-img-original")
                            if img_el.count():
                                main_image_url = img_el.get_attribute("src")
                            if not main_image_url:
                                img_el = detail_page.locator(".main-slide .swiper-slide img").first
                                if img_el.count():
                                    main_image_url = img_el.get_attribute("src")
                            if not main_image_url:
                                main_image_url = list_img_url
                        except:
                            main_image_url = list_img_url

                        # --- Extract Main Logic Item ID ---
                        main_item_id = None
                        match = re.search(r'/p/([^?&/]+)', product_url)
                        if match:
                            main_item_id = match.group(1)

                        # --- Determine Brand ---
                        # 1. From Specs
                        # --- Determine Brand ---
                        # 1. Strict Spec Extraction
                        brand_name = specs_dict.get("Brand") or specs_dict.get("Manufacturer")
                        
                        if not brand_name:
                            print(f"Skipping {title[:30]}... No Brand specified.")
                            continue
                        
                        # Normalize brand name
                        brand_name = brand_name.strip().title()
                        
                        # Get or Create Brand
                        brand_obj = session.query(Brand).filter_by(name=brand_name).first()
                        if not brand_obj:
                            try:
                                brand_obj = Brand(name=brand_name)
                                session.add(brand_obj)
                                session.commit()
                                print(f"Created new brand: {brand_name}")
                            except:
                                session.rollback()
                                # Retry fetch in case of race condition
                                brand_obj = session.query(Brand).filter_by(name=brand_name).first()

                        if not brand_obj:
                             print(f"Failed to determine/create brand for {title}")
                             continue

                        # --- Save Main Laptop ---
                        existing = None
                        if main_item_id:
                            existing = session.query(Product).filter_by(item_id=main_item_id).first()
                        if not existing:
                            existing = session.query(Product).filter_by(url=product_url).first()

                        product_id = None
                        
                        if existing:
                            product_id = existing.id
                            print(f"Updating existing ({brand_name}): {title[:15]}")
                            if not existing.item_id and main_item_id:
                                existing.item_id = main_item_id
                            if not existing.image_url and main_image_url:
                                existing.image_url = main_image_url
                            
                            # Update brand if incorrect (e.g. was previously "Newest" or "Refurbished")
                            if existing.brand_id != brand_obj.id:
                                existing.brand_id = brand_obj.id
                                print(f"  -> Correcting brand to {brand_name}")
                                
                            session.commit()
                        else:
                            try:
                                laptop = Product(
                                    brand_id=brand_obj.id,
                                    title=title,
                                    price=price,
                                    url=product_url,
                                    item_id=main_item_id,
                                    image_url=main_image_url
                                )
                                session.add(laptop)
                                session.commit()
                                product_id = laptop.id
                                
                                for k, v in specs_dict.items():
                                    spec = Specification(product_id=product_id, key=k, value=v)
                                    session.add(spec)
                                session.commit()
                            except Exception as e:
                                session.rollback()
                                print(f"Error saving product: {e}")
                                continue

                        # --- 2. Scrape Variants ---
                        variants_found = []
                        
                        # User-provided HTML structure: ul.form-cells > li.form-cell > div.form-option-item
                        try:
                            variant_items = detail_page.locator("ul.form-cells li.form-cell .form-option-item").all()
                            for item in variant_items:
                                # Name and Price
                                title_div = item.locator(".form-checkbox-title")
                                if title_div.count():
                                    # Extract Price from strong tag
                                    price_strong = title_div.locator("strong")
                                    v_price = "N/A"
                                    if price_strong.count():
                                        v_price = price_strong.first.inner_text().strip()
                                    
                                    # Get full text and clean up name
                                    full_text = title_div.inner_text()
                                    # Remove price from name if present
                                    if v_price != "N/A" and v_price in full_text:
                                        v_name = full_text.replace(v_price, "").replace("|", "").strip()
                                        # Clean up trailing pipes or spaces
                                        v_name = v_name.rstrip(" |")
                                    else:
                                        v_name = full_text
                                        
                                    # Variant Image
                                    v_img = item.get_attribute("data-img")

                                    # Construct URL:
                                    item_id = item.get_attribute("data-item4build")
                                    keywords = item.get_attribute("data-urlkeywords")
                                    
                                    v_url = None
                                    if item_id:
                                        kw = keywords if keywords else "product"
                                        v_url = f"https://www.newegg.com/{kw}/p/{item_id}"
                                    
                                    # Parse Memory and Storage from full_text OR v_name
                                    # Typical string: "I5-1135G7 / 16GB Ram|256GB SSD"
                                    # Regex for Memory: (\d+\s?GB)\s*(Ram|Memory)
                                    # Regex for Storage: (\d+\s?(GB|TB))\s*(SSD|HDD|NVMe)
                                    # Regex for Processor: (i[3579]-?\d{4,5}[A-Z]*|Ryzen\s?\d|M[123]\s?(Pro|Max|Ultra)?|Intel\s?Core\s?i[3579])
                                    
                                    v_memory = None
                                    v_storage = None
                                    v_processor = None
                                    
                                    # Use full_text for better context
                                    mem_match = re.search(r'(\d+\s?GB)\s*(Ram|Memory)', full_text, re.IGNORECASE)
                                    if mem_match:
                                        v_memory = mem_match.group(1).replace(" ","")
                                        
                                    sto_match = re.search(r'(\d+\s?(GB|TB))\s*(SSD|HDD|NVMe|Storage)', full_text, re.IGNORECASE)
                                    if sto_match:
                                        v_storage = sto_match.group(1).replace(" ","")

                                    # Processor: Match common patterns
                                    # i5-1135G7, i7-12700H, Ryzen 5, Ryzen 7, M1, M2
                                    # Also handle "I5" vs "i5"
                                    proc_match = re.search(r'((Core\s?)?i[3579]-?\d{4,5}[A-Z\d]*|Ryzen\s?\d\s?\d*|M[123]\s?(Pro|Max|Ultra)?)', full_text, re.IGNORECASE)
                                    if proc_match:
                                        v_processor = proc_match.group(1).strip()

                                    if v_url:
                                        variants_found.append({
                                            "url": v_url,
                                            "name": v_name,
                                            "price": v_price,
                                            "memory": v_memory,
                                            "storage": v_storage,
                                            "processor": v_processor,
                                            "image_url": v_img
                                        })
                        except Exception as e:
                            print(f"Error parsing variants: {e}")

                        # Fallback to previous logic if nothing found (just in case)
                        if not variants_found:
                            option_groups = detail_page.locator(".product-options ul.options-list").all()
                            for group in option_groups:
                                items = group.locator("li").all()
                                for item in items:
                                    link = item.locator("a")
                                    if link.count():
                                        v_url = link.get_attribute("href")
                                        v_text = link.get_attribute("title") or link.inner_text()
                                        if v_url and "newegg.com" in v_url:
                                            variants_found.append({
                                                "url": v_url,
                                                "name": v_text,
                                                "price": "See URL"
                                            })

                        print(f"Found {len(variants_found)} variants")
                        for var_data in variants_found:
                            # Check if duplicate
                            chk = session.query(Variant).filter_by(product_id=product_id, url=var_data['url']).first()
                            if not chk:
                                v_obj = Variant(
                                    product_id=product_id,
                                    name=var_data['name'],
                                    price=var_data['price'],
                                    url=var_data['url'],
                                    memory=var_data.get('memory'),
                                    storage=var_data.get('storage'),
                                    processor=var_data.get('processor'),
                                    image_url=var_data.get('image_url')
                                )
                                session.add(v_obj)
                        session.commit()
                        
                        # --- 3. Delay ---
                        print("Waiting 2s...")
                        time.sleep(2)
                        
                    except Exception as e:
                        print(f"Error scraping details {product_url}: {e}")
                    finally:
                        # detail_page.close() # Keep open for reuse
                        pass

                except Exception as e:
                    print(f"Error processing cell: {e}")

            # Pagination
            try:
                # User provided HTML: <div class="btn-group-cell"><a ... title="Next">
                # Select first unique one to avoid strict mode error (top and bottom pagination)
                next_btn = page.locator("a[title='Next']").first
                if not next_btn.count():
                    # Try class based if title fails (backup)
                    next_btn = page.locator(".btn-group-cell a i.fa-caret-right").locator("..").first
                
                if next_btn.count() and not next_btn.is_disabled():
                    current_page_num += 1
                    # next_btn.click() # caused interception errors. 
                    # The loop automatically navigates to the next page URL at the start of the while loop.
                    pass 
                else:
                    print("No next page found or disabled.")
                    has_next_page = False
            except Exception as e:
                print(f"Error checking pagination (Browser might be closed): {e}")
                has_next_page = False
                break

        browser.close()

if __name__ == "__main__":
    scrape_newegg()
