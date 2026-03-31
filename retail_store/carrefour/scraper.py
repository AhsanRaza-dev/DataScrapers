import asyncio
import logging
import json
import os
import argparse
from playwright.async_api import async_playwright
from database import init_db, get_session, save_product

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def extract_product_details(page, product_info):
    product_url = product_info['url']
    logger.info(f"Navigating to product: {product_url}")
    await page.goto(product_url, timeout=60000)
    
    # Wait for the H1 title to be present to ensure React has loaded the page data
    try:
        await page.wait_for_selector('h1', timeout=10000)
    except Exception:
        logger.warning(f"Timeout waiting for h1 on {product_url}")
        
    await asyncio.sleep(2) # Extra buffer for elements to attach

    name = "Unknown"
    selling_price = 0.0

    try:
        name_el = await page.query_selector('h1')
        if name_el:
            name = await name_el.inner_text()
            
        # Try finding the large price text
        price_text = await page.evaluate('''() => {
            let h2s = Array.from(document.querySelectorAll('h2'));
            let priceH2 = h2s.find(h => h.innerText.includes('AED'));
            if (priceH2) return priceH2.innerText;
            
            let divs = Array.from(document.querySelectorAll('div'));
            let priceDiv = divs.find(d => d.innerText.includes('AED') && d.innerText.length < 15);
            if (priceDiv) return priceDiv.innerText;
            
            return "0.0";
        }''')
        
        selling_price_str = ''.join(c for c in price_text if c.isdigit() or c == '.')
        if selling_price_str:
            selling_price = float(selling_price_str)
            
    except Exception as e:
        logger.error(f"Error parsing name/price: {e}")

    brand = None
    try:
        brand = await page.evaluate('''() => {
            let moreFromSpan = Array.from(document.querySelectorAll('span')).find(s => s.innerText.trim() === 'More From');
            if (moreFromSpan && moreFromSpan.nextElementSibling) {
                return moreFromSpan.nextElementSibling.innerText.trim();
            }
            return null;
        }''')
    except Exception as e:
        logger.error(f"Error parsing brand: {e}")

    variants = []
    try:
        variants = await page.evaluate('''() => {
            let res = [];
            let rows = Array.from(document.querySelectorAll('div.flex.flex-row'));
            for (let row of rows) {
                let spans = row.querySelectorAll('span');
                if (spans.length >= 2 && spans[0].innerText.includes(':')) {
                    let name = spans[0].innerText.replace(':', '').trim();
                    let value = spans[1].innerText.trim();
                    if (name && value) {
                        res.push({name, value});
                    }
                }
            }
            return res;
        }''')
    except Exception as e:
        logger.error(f"Error parsing variants: {e}")

    sku_raw = product_url.split('/')[-1] if '/' in product_url else "UNKNOWN"
    sku_clean = sku_raw.split('?')[0]
    
    product_data = {
        "url": product_url,
        "name": name,
        "selling_price": selling_price,
        "sku": sku_clean,
        "category": product_info.get("category", "Uncategorized"), 
        "subcategory": product_info.get("subcategory", ""),
        "brand": brand,
        "variants": variants,
        "storage_conditions": "",
        "allergy_advice": "",
        "brand_marketing_message": ""
    }
    
    if name == "Unknown":
        logger.warning(f"Name unknown for {product_url}")

    # Extract Information Block 
    items = await page.query_selector_all('div.text-md.leading-5.font-bold')
    for item in items:
        title = (await item.inner_text()).strip()
        if title in ["Storage Conditions", "Allergy Advice", "Brand Marketing Message"]:
            val_el = await item.evaluate_handle('node => node.nextElementSibling')
            if val_el:
                val = await val_el.inner_text()
                if title == "Storage Conditions":
                    product_data['storage_conditions'] = val.strip()
                elif title == "Allergy Advice":
                    product_data['allergy_advice'] = val.strip()
                elif title == "Brand Marketing Message":
                    product_data['brand_marketing_message'] = val.strip()

    return product_data

async def extract_links_from_current_view(page):
    links = await page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a'))
                    .map(a => a.href)
                    .filter(href => href.includes('/p/'));
    }''')
    unique = list(set([l for l in links if "carrefouruae.com" in l]))
    logger.info(f"Extracted {len(unique)} product links from current view.")
    return unique

async def load_all_products_on_page(page, test_run=False):
    logger.info("Extracting products and clicking 'Load More' if present...")
    all_links = set()
    
    # Grab initial links
    initial_links = await extract_links_from_current_view(page)
    all_links.update(initial_links)

    clicks = 0
    while True:
        if test_run and clicks >= 2:
            logger.info("Test run: limiting 'Load More' clicks to 2.")
            break
        try:
            # We look for a button containing "Load More"
            # Using xpath or text selector based on user provided html snippet
            load_more = page.locator('button:has-text("Load More")')
            if await load_more.count() > 0 and await load_more.first.is_visible():
                await load_more.first.scroll_into_view_if_needed()
                await load_more.first.click()
                clicks += 1
                logger.info(f"Clicked 'Load More' ({clicks})")
                await asyncio.sleep(4)
                
                # Grab new links revealed after load more
                new_links = await extract_links_from_current_view(page)
                all_links.update(new_links)
            else:
                break
        except Exception as e:
            logger.warning(f"Stopped loading more: {e}")
            break

    return list(all_links)

async def fetch_products_from_category(page, category_url, test_run=False):
    logger.info(f"Navigating to category: {category_url}")
    await page.goto(category_url, timeout=60000)
    await page.wait_for_load_state('domcontentloaded')
    await asyncio.sleep(5)
    
    # Extract Category Name
    cat_name = "Unknown Category"
    try:
        cat_el = await page.query_selector('h1')
        if cat_el:
            cat_name = await cat_el.inner_text()
            cat_name = cat_name.strip()
    except Exception:
        pass
        
    product_links = []
    seen_urls = set()
    
    # Check for subcategories slider
    try:
        # Wait for the group role to appear, which indicates the slider mounted
        await page.wait_for_selector('div[role="group"] button', timeout=15000)
        sub_buttons = await page.locator('div[role="group"] button').all()
    except Exception:
        logger.warning(f"Timeout waiting for subcategories on {category_url}")
        sub_buttons = []
        
    if not sub_buttons:
        logger.info("No subcategory buttons found. Scraping current category page directly.")
        links = await load_all_products_on_page(page, test_run)
        for l in links:
            if l not in seen_urls:
                seen_urls.add(l)
                product_links.append({"url": l, "category": cat_name, "subcategory": ""})
    else:
        logger.info(f"Found {len(sub_buttons)} subcategory tabs.")
        limit = 2 if test_run else len(sub_buttons)
        for idx in range(limit):
            # Re-fetch locators to avoid stale elements
            buttons = await page.locator('div[role="group"] button').all()
            if idx >= len(buttons):
                break
            btn = buttons[idx]
            
            try:
                # Based on user HTML, text is in div with class "text-xs" or "text-black" inside the button
                text = await btn.inner_text()
                name = text.strip().replace('\\n', ' ') if text else f"Tab {idx}"
                
                if name.lower() == "all":
                    logger.info("Skipping 'All' tab to avoid cross-category duplicates.")
                    continue
                    
                logger.info(f"Clicking subcategory tab: {name}")
                
                await btn.scroll_into_view_if_needed()
                await btn.click()
                
                # We must wait for React to load the new products
                await asyncio.sleep(5)
                
                # Check to see if we reached the end of the list and ensure there are actual products
                try:
                     await page.wait_for_selector('a[href*="/p/"]', timeout=10000)
                except Exception:
                     logger.warning("No products found for this subcategory tab.")
                     
            except Exception as e:
                logger.error(f"Error clicking subcategory tab {idx}: {e}")
                
            links = await load_all_products_on_page(page, test_run)
            for l in links:
                if l not in seen_urls:
                    seen_urls.add(l)
                    product_links.append({"url": l, "category": cat_name, "subcategory": name})
            
    return product_links

async def run_scraper(test_run=False):
    logger.info("Initializing database...")
    init_db()
    session = get_session()
    
    cat_file = "d:/curiologix/retail_store/carrefour/categories.json"
    if not os.path.exists(cat_file):
        logger.error(f"Categories file not found: {cat_file}")
        return
        
    with open(cat_file, 'r', encoding='utf-8') as f:
        categories = json.load(f)
        
    if not categories:
        logger.error("No categories found in categories.json")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--window-size=1920,1080'
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        
        # Additional obfuscation 
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = await context.new_page()
        
        for cat_url in categories[:1] if test_run else categories:
            logger.info(f"--- Starting Category: {cat_url} ---")
            product_urls = await fetch_products_from_category(page, cat_url, test_run)
            
            logger.info(f"Total unique products found in category: {len(product_urls)}")
            
            # Limit if test_run
            target_products = product_urls[:3] if test_run else product_urls
            
            for p_info in target_products:
                p_data = await extract_product_details(page, p_info)
                logger.info(f"Extracted Details: {p_data['name']} (Price: {p_data['selling_price']}) - Cat: {p_data['category']} / Sub: {p_data['subcategory']}")
                try:
                    save_product(session, p_data)
                    logger.info("Saved to DB.")
                except Exception as e:
                    logger.error(f"Failed to save DB for {p_info['url']}: {e}")
                    session.rollback()

        logger.info("Scrape finished. Closing browser.")
        await browser.close()
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-run', action='store_true', help='Run a small sample scrape')
    args = parser.parse_args()
    
    asyncio.run(run_scraper(test_run=args.test_run))
