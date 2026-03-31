import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

async def test_product_scrape():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = await context.new_page()
        
        # Using a known product URL that likely has a table for specifications
        url = "https://www.costco.com/rastellis-gourmet-usda-choice-black-angus-ribeye-steaks-14-x-8-oz.product.100989065.html"
        await page.goto(url, wait_until="commit", timeout=30000)
        await page.wait_for_timeout(3500)
        
        # Get Description
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        # Get Description and Instructions
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
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
            
        print("------- DESCRIPTION -------")
        print(description[:300] + "...")
        print("\n------- INSTRUCTIONS -------")
        print(instructions[:300] + "...")
        
        # Get Specifications
        specs = {}
        await page.evaluate("""() => {
            let specBtn = document.getElementById('specifications');
            if(specBtn && specBtn.getAttribute('aria-expanded') !== 'true') {
                specBtn.click();
            }
        }""")
        await page.wait_for_timeout(2000)
        
        updated_content = await page.content()
        spec_soup = BeautifulSoup(updated_content, 'html.parser')
        
        spec_btn = spec_soup.find('button', id='specifications')
        panel = None
        if spec_btn:
            if spec_btn.has_attr('aria-controls'):
                panel = spec_soup.find(id=spec_btn['aria-controls'])
            if not panel:
                panel = spec_btn.find_next_sibling('div')
                
        if panel:
            table = panel.find('table', id='ProductSpecifications')
            if not table:
                table = spec_soup.find('table', id='ProductSpecifications')
                
            if table:
                rows = table.find_all('tr')
                for row in rows:
                    th = row.find('th')
                    td = row.find('td')
                    if th and td:
                        specs[th.text.strip()] = td.text.strip()
            else:
                rows = panel.find_all(attrs={"data-testid": "Grid"})
                for r in rows:
                    cols = r.find_all(attrs={"data-testid": "Grid"})
                    if len(cols) == 2:
                        specs[cols[0].text.strip()] = cols[1].text.strip()
                if not specs:
                    text_blocks = panel.find_all('div', attrs={"data-testid": "Text"})
                    if text_blocks:
                        for i in range(0, len(text_blocks)-1, 2):
                            specs[text_blocks[i].text.strip()] = text_blocks[i+1].text.strip()
                                
        print("\n------- SPECIFICATIONS -------")
        for k, v in specs.items():
            print(f"{k}: {v}")
            
        await page.close()

if __name__ == "__main__":
    asyncio.run(test_product_scrape())
