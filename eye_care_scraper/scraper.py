
import os
import json
import time
import argparse
import re
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.warbyparker.com/sunglasses"

def scrape_product(page, url):
    print(f"Scraping {url}...")
    try:
        page.goto(url, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2) # Wait for dynamic content
    except Exception as e:
        print(f"Failed to load {url}: {e}")
        return None

    data = {
        "url": url,
        "name": None,
        "price": None,
        "image_url": None,

        "colors": [],
        "width_options": [],
        "measurements": {
            "Lens width": None, 
            "Bridge": None, 
            "Temple length": None,
            "Frame Width": None
        }
    }

    try:
        # Name: Usually an H1
        name_locator = page.locator("h1").first
        if name_locator.is_visible():
            data["name"] = name_locator.inner_text().strip()
            
        # Image URL
        image_el = page.locator('meta[property="og:image"]').first
        if image_el.count() > 0:
             data["image_url"] = image_el.get_attribute("content")
    except Exception as e:
        print(f"Error getting name/image: {e}")

    # Helper to get price
    def get_current_price():
        try:
             # Strategy 1: User provided class
             elements = page.locator("[class*='html-text_container']").all()
             for el in elements:
                 text = el.inner_text().strip()
                 if "$" in text:
                     return text
             
             # Strategy 2: "Starting at" text
             el = page.locator("div", has_text=re.compile(r"Starting at\s*\$[0-9]+")).first
             if el.count() > 0:
                 return el.inner_text().strip()

             return None
        except Exception as e:
            print(f"Error finding price: {e}")
            return None

    # Initial Price
    data["price"] = get_current_price()
    if not data["price"]:
        print("Price not found...") 

    # 1. Width Options
    try:
        print("Looking for width options...")
        potential_widths = page.locator("[class*='wp-uiparagraph300']").all()
        found_widths = set()
        
        for el in potential_widths:
            text = el.inner_text().strip()
            if text in ["Extra Narrow", "Narrow", "Medium", "Wide", "Extra Wide"]:
                found_widths.add(text)
            elif re.match(r"^\d+\s*mm$", text):
                data["measurements"]["Frame Width"] = text
        
        data["width_options"] = list(found_widths)
        print(f"Found widths: {data['width_options']}")
    except Exception as e:
        print(f"Error getting widths: {e}")

    # 2. Measurements
    try:
        print("Looking for Measurements button...")
        measure_btn = page.locator("button", has_text="Measurements").or_(page.locator("button", has_text="Other measurements"))
        if measure_btn.count() > 0 and measure_btn.first.is_visible():
            print("Clicking Measurements button...")
            measure_btn.first.click()
            time.sleep(2) # Wait for popup
            
            # Locate table
            print("Looking for measurements table...")
            table = page.locator("table", has_text="Lens width").first
            if table.is_visible():
                print("Table found.")
                headers = table.locator("th").all_inner_texts()
                headers = [h.strip() for h in headers]
                cells = table.locator("td").all_inner_texts()
                
                current_cell_idx = 0
                for h in headers:
                    if h in ["Lens width", "Bridge", "Temple length", "Temple width"]:
                        if current_cell_idx < len(cells):
                            data["measurements"][h] = cells[current_cell_idx].strip()
                            current_cell_idx += 1
            else:
                 print("Table with Lens width not found, trying fallback...")
                 for key in ["Lens width", "Bridge", "Temple length", "Temple width"]: 
                    label = page.get_by_text(key, exact=False).first
                    if label.is_visible():
                        parent_text = label.locator("..").inner_text()
                        data["measurements"][key] = parent_text.replace("\n", " ").strip()

            page.keyboard.press("Escape")
            time.sleep(1)
        else:
            print("Measurements button not found.")
    except Exception as e:
        print(f"Error scraping measurements: {e}")



    # 3. Colors (Interaction)
    try:
        print("Iterating colors...")
        color_group = page.locator('div[role="radiogroup"]')
        if color_group.count() > 0:
            buttons = color_group.first.locator("button").all()
            for btn in buttons:
                color_name = btn.get_attribute("aria-label")
                if color_name:
                    is_checked = btn.get_attribute("aria-checked") == "true"
                    current_color_price = data["price"] # Default
                    
                    if not is_checked:
                        try:
                            btn.click()
                            time.sleep(1)
                            new_price = get_current_price()
                            if new_price:
                                current_color_price = new_price
                        except Exception as e:
                            print(f"Error clicking color {color_name}: {e}")
                    
                    data["colors"].append({
                        "name": color_name,
                        "price": current_color_price
                    })
    except Exception as e:
        print(f"Error getting matching colors/prices: {e}")

    return data

def run_scraper(limit=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False) 
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"Navigating to {BASE_URL}")
        try:
            page.goto(BASE_URL, timeout=90000)
        except Exception as e:
            print(f"Initial navigation failed: {e}")
            return

        # Scroll to load all items
        print("Scrolling to load all items...")
        
        def count_visible_products():
            return page.locator("a[href*='/sunglasses/']").count()

        # Pagination Strategy: URL Parameters
        # The user confirmed proper behavior with ?page=N.
        # This is more robust than clicking buttons.
        
        print("Starting URL-based pagination loop...")
        product_urls = set()
        
        blacklist = [
            "https://www.warbyparker.com/sunglasses/men",
            "https://www.warbyparker.com/sunglasses/women",
            "https://www.warbyparker.com/sunglasses"
        ]
        
        max_pages = 20 # Safety limit, screenshot showed ~14 pages
        
        for page_num in range(1, max_pages + 1):
            current_url = f"{BASE_URL}?page={page_num}"
            print(f"Scraping Page {page_num}: {current_url}")
            
            try:
                # Go to the page
                page.goto(current_url, timeout=60000)
                
                # Check for "no results" text just in case
                if page.locator("text=No results found").is_visible():
                    print("No results found page reached.")
                    break

                # Wait for products to be attached to DOM (don't strictly wait for visibility as overlays might block)
                try:
                    page.wait_for_selector("a[href*='/sunglasses/']", state="attached", timeout=10000)
                except:
                    print(f"Warning: Timeout waiting for selector on page {page_num}, but attempting extraction anyway...")
                
                # Small scroll to trigger lazy loading if needed
                # print("Triggering lazy load...")
                # page.mouse.wheel(0, 3000) 
                # time.sleep(2)
                page.keyboard.press("End")
                time.sleep(2)
                
            except Exception as e:
                print(f"Error navigating to page {page_num}: {e}")
                # If navigation completely failed (e.g. network), we might want to retry or skip
                # checking if we can scrape anyway

            # Extract links
            hrefs = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a')).map(a => a.href);
            }""")
            
            count_on_page = 0
            new_items_found = False
            
            for href in hrefs:
                 if href and "/sunglasses/" in href:
                     parts = href.strip("/").split("/")
                     if len(parts) >= 3:
                         if href not in product_urls and href not in blacklist:
                             product_urls.add(href)
                             count_on_page += 1
                             new_items_found = True
            
            print(f"Found {count_on_page} new products on page {page_num}. Total unique: {len(product_urls)}")
            
            # Stop if no new products found on a page (end of list)
            if not new_items_found and page_num > 1:
                print("No new products found. Assuming end of pagination.")
                break
        

        
        # Initialize DB
        try:
            import database
            database.init_db()
        except ImportError:
            print("Database module not found. ensure database.py is in the directory.")
            return

        count = 0
        for url in product_urls:
            if limit and count >= limit:
                break
            
            # Deduplication
            if database.product_exists(url):
                print(f"Skipping {url} (already exists)")
                continue

            data = scrape_product(page, url)
            if data:
                # Save to DB immediately
                database.save_product(data)
                count += 1
                
        browser.close()
        print("Scraping completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Limit number of products to scrape")
    args = parser.parse_args()
    
    run_scraper(args.limit)
