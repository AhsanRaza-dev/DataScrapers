import asyncio
import argparse
import random
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from models import SessionLocal
from db_manager import save_product
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def run_scraper(test_mode=False, port=None):
    async with async_playwright() as p:
        if port:
            logger.info(f"Connecting to existing Chrome instance on port {port} (127.0.0.1)")
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0]
            page = await context.new_page()
        else:
            logger.info("Launching new Chrome instance (visible)")
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
        
        main_url = "https://www.costco.com/grocery-household.html"
        logger.info(f"Navigating to Top Level: {main_url}")
        try:
            await page.goto(main_url, wait_until="commit", timeout=30000)
        except Exception as e:
            logger.warning(f"Navigation to {main_url} timed out or failed, proceeding anyway: {e}")
        await page.wait_for_timeout(5000)
        
        # Give it a moment to render JS
        await asyncio.sleep(3)
        
        try:
            await page.wait_for_selector('div[data-testid="costco-ad-set-multi-row"] a', timeout=10000)
        except Exception as e:
            logger.error(f"Failed to find categories: {e}")
            await browser.close()
            return
            
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        container = soup.find('div', {'data-testid': 'costco-ad-set-multi-row'})
        if not container:
            logger.error("Category container not found")
            await browser.close()
            return

        links = container.find_all('a', href=True)
        unique_links = []
        for l in links:
            href = l['href']
            if href.startswith('/'):
                href = f"https://www.costco.com{href}"
            
            text_div = l.find('div', {'data-testid': 'Text'})
            cat_name = text_div.text.strip() if text_div else "Unknown"

            if href not in [u['href'] for u in unique_links]:
                unique_links.append({'href': href, 'name': cat_name})

        # Skip the first 3 categories
        if len(unique_links) > 3:
            categories_to_scrape = unique_links[3:]
        else:
            categories_to_scrape = []
            
        logger.info(f"Found {len(categories_to_scrape)} top-level categories to scrape.")
        
        session = SessionLocal() if not test_mode else None
        
        seen_products = set()
        try:
            for cat in categories_to_scrape:
                logger.info(f"Traversing hierarchy starting at: {cat['name']}")
                await traverse_category(page, cat['href'], [cat['name']], session, test_mode, seen_products)
                await asyncio.sleep(random.uniform(2, 4))
                
        finally:
            if session:
                session.close()
            await browser.close()

async def traverse_category(page, url, category_path, session, test_mode, seen_products, visited_categories=None):
    """
    Recursively look for subcategories. If none, scrape products on this page.
    """
    if visited_categories is None:
        visited_categories = set()
        
    # Prevent infinite loops from cross-linked categories (e.g., Flowers -> Gift Baskets -> Flowers)
    if url in visited_categories or len(category_path) > 7:
        logger.info(f"Skipping already visited or over-nested category: {' -> '.join(category_path)}")
        return
        
    visited_categories.add(url)
    
    try:
        await page.goto(url, wait_until="commit", timeout=30000)
    except Exception as e:
        logger.warning(f"Navigation to {url} failed: {e}")
    await page.wait_for_timeout(5000)
    await asyncio.sleep(2)
    
    subcats = []
    if len(category_path) < 2:
        # Check if this category has subcategories (Shop by Category, Shop By Cut, etc)
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        # Based on HTML structure, Costco uses "costco-ad-set-multi-row" for subcategories too.
        containers = soup.find_all('div', {'data-testid': 'costco-ad-set-multi-row'})
        
        if containers:
            for container in containers:
                links = container.find_all('a', href=True)
                for l in links:
                    href = l['href']
                    if href.startswith('/'):
                        href = f"https://www.costco.com{href}"
                    text_div = l.find('div', {'data-testid': 'Text'})
                    if text_div and len(text_div.text.strip()) > 2:
                        cat_name = text_div.text.strip()
                        if href not in [s['href'] for s in subcats]:
                            subcats.append({'href': href, 'name': cat_name})
                            
        if subcats and len(subcats) > 0:
            logger.info(f"Found {len(subcats)} Subcategories in {' -> '.join(category_path)}")
            for subcat in subcats:
                new_path = list(category_path)
                new_path.append(subcat['name'])
                await traverse_category(page, subcat['href'], new_path, session, test_mode, seen_products, visited_categories)
            return
            
    # If no obvious subcategories found, or we reached max depth, scrape products.
    logger.info(f"Scraping products for Category: {' -> '.join(category_path)}")
    await collect_and_scrape_products(page, category_path, session, test_mode, seen_products)


async def collect_and_scrape_products(page, category_path, session, test_mode, seen_products):
    page_num = 1
    product_urls = []
    
    # 1. Collect all product URLs across pagination
    while True:
        logger.info(f"Gathering URLs from {' -> '.join(category_path)} - Page {page_num}")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        await asyncio.sleep(2)
        
        try:
            await page.wait_for_selector('[data-testid="Grid"] a, .product-list a', timeout=10000)
        except:
            logger.warning("Timeout waiting for products grid to load.")
            pass

        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        products = soup.find_all('a', href=True)
        for prod_link in products:
            prod_name = prod_link.text.strip()
            prod_url = prod_link.get('href', '')
            
            # Skip invalid, short, or non-product links
            if not prod_url or len(prod_name) < 5:
                continue
                
            if 'product.' not in prod_url and '.html' not in prod_url:
                continue
                
            if prod_url == "/" or "grocery-household.html" in prod_url:
                continue
                
            if not any(char.isdigit() for char in prod_url):
                continue
                
            if prod_url.startswith('/'):
                prod_url = f"https://www.costco.com{prod_url}"
                
            if prod_url not in product_urls and prod_url not in seen_products:
                product_urls.append(prod_url)
                
        # Handle pagination
        next_button = soup.find('button', attrs={"aria-label": "Go to next page"})
        if next_button:
            if 'disabled' in next_button.attrs:
                break
            else:
                try:
                    await page.click('button[aria-label="Go to next page"]')
                    page_num += 1
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    logger.warning(f"Failed to click next page: {e}")
                    break
        else:
            break
            
    logger.info(f"Gathered {len(product_urls)} unique new products in {' -> '.join(category_path)}.")
    
    # 2. Deep Scrape each product URL
    for purl in product_urls:
        if purl == "https://www.costco.com": continue
        
        seen_products.add(purl)
        await deep_scrape_product(page, purl, category_path, session, test_mode)
        await asyncio.sleep(random.uniform(1, 3))

async def deep_scrape_product(page, prod_url, category_path, session, test_mode):
    try:
        await page.goto(prod_url, wait_until="commit", timeout=30000)
    except Exception as e:
        logger.warning(f"Failed to load product page {prod_url}: {e}")
        return
    await page.wait_for_timeout(3500)
    
    content = await page.content()
    soup = BeautifulSoup(content, 'html.parser')

    # Get Name
    title_el = soup.find('h1', attrs={"automation-id": "productName"}) or soup.find('h1')
    prod_name = title_el.text.strip() if title_el else "Unknown Product"
    if prod_name == "Unknown Product" or "costco homepage" in prod_name.lower() or "access denied" in prod_name.lower() or "not found" in prod_name.lower():
        return # Probably a dead page, homepage, or bot block
        
    sku = "UNKNOWN-SKU"
    sku_match = re.search(r'\.(\d+)\.html', prod_url)
    if sku_match:
        sku = sku_match.group(1)
        
    # Get Description and Instructions
    desc_node = soup.find('div', id='product-details-summary')
    description = ""
    instructions = ""
    if desc_node:
        full_text = desc_node.get_text(separator='\n', strip=True)
        if "Preparation Instructions:" in full_text:
            parts = full_text.split("Preparation Instructions:")
            description = parts[0].strip()
            instructions = parts[1].strip()
        elif "Instructions:" in full_text:
            parts = full_text.split("Instructions:")
            description = parts[0].strip()
            instructions = parts[1].strip()
        else:
            description = full_text
    else:
        description = "No description available"
    
    # Get Specifications
    specs = {}
    try:
        # Click the specifications accordion if not expanded
        await page.evaluate("""() => {
            let specBtn = document.getElementById('specifications');
            if(specBtn && specBtn.getAttribute('aria-expanded') !== 'true') {
                specBtn.click();
            }
        }""")
        await page.wait_for_timeout(1000)
        
        updated_content = await page.content()
        spec_soup = BeautifulSoup(updated_content, 'html.parser')
        
        spec_btn = spec_soup.find('button', id='specifications')
        panel = None
        if spec_btn:
            if spec_btn.has_attr('aria-controls'):
                panel = spec_soup.find(id=spec_btn['aria-controls'])
            if not panel:
                panel = spec_btn.find_next_sibling('div')
                
        table = spec_soup.find('table', id='ProductSpecifications')
        
        if table:
            rows = table.find_all('tr')
            for row in rows:
                th = row.find('th')
                td = row.find('td')
                if th and td:
                    specs[th.text.strip()] = td.text.strip()
        elif panel:
                # Fallback to Grid Layout
                rows = panel.find_all(attrs={"data-testid": "Grid"})
                for r in rows:
                    cols = r.find_all(attrs={"data-testid": "Grid"})
                    if len(cols) == 2:
                        key = cols[0].text.strip()
                        val = cols[1].text.strip()
                        if key and val:
                            specs[key] = val
                            
                # Ultimate Fallback
                if not specs:
                    text_blocks = panel.find_all('div', attrs={"data-testid": "Text"})
                    if text_blocks:
                        for i in range(0, len(text_blocks)-1, 2):
                            specs[text_blocks[i].text.strip()] = text_blocks[i+1].text.strip()
    except Exception as e:
        logger.warning(f"Failed to parse specs cleanly: {e}")

    brand = specs.get('Brand', '')
    if not brand:
        brand = specs.get('Brand Name', '')

    product_data = {
        'name': prod_name,
        'brand': brand,
        'categories': category_path, # Using recursive path!
        'sku': sku,
        'barcode': '', 
        'description': description,
        'instructions': instructions,
        'unit': 'piece', 
        'stockQuantity': 100,
        'minStock': 10,
        'isActive': True,
        'hasVariants': False,
        'specifications': specs
    }

    if test_mode:
        spec_count = len(specs.keys())
        logger.info(f"[TEST] Extracted: {prod_name} | SKU: {sku} | Cats: {'->'.join(category_path)} | Specs: {spec_count}")
    else:
        save_product(session, product_data)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-mode", action="store_true", help="Run without saving to DB")
    parser.add_argument("--port", type=int, default=None, help="Connect to existing Chrome debugging port (e.g. 9222) to bypass captchas")
    args = parser.parse_args()
    
    asyncio.run(run_scraper(test_mode=args.test_mode, port=args.port))
