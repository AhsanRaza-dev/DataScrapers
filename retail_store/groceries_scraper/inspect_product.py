import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import json

async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        
        page = context.pages[0]
        for p_test in context.pages:
            if "costco.com" in p_test.url and ("product." in p_test.url or ".html" in p_test.url):
                page = p_test
                break
                
        print(f"Inspecting Product URL: {page.url}")
        
        # Click specifications if it exists
        await page.evaluate("""() => {
            let specBtn = document.getElementById('specifications');
            if(specBtn && specBtn.getAttribute('aria-expanded') !== 'true') {
                specBtn.click();
            }
        }""")
        await page.wait_for_timeout(2000)
        
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        desc = soup.find(id="product-details-summary")
        print("--- DESCRIPTION HTML ---")
        if desc:
            print(str(desc)[:500] + "...")
        else:
            print("Description not found")
            
        print("\n--- SPECIFICATIONS CONTENT ---")
        spec_btn = soup.find('button', id='specifications')
        if spec_btn and spec_btn.has_attr('aria-controls'):
            panel = soup.find(id=spec_btn['aria-controls'])
            if panel:
                print(str(panel)[:1000] + "...")
                
                # Attempt to find key-value rows
                # Costco often uses MUI Grids for specs
                rows = panel.find_all(attrs={"data-testid": "Grid"})
                print("\n--- Spec Rows Extraction Test ---")
                for r in rows:
                    cols = r.find_all(attrs={"data-testid": "Grid"})
                    if len(cols) == 2:
                        key = cols[0].text.strip()
                        val = cols[1].text.strip()
                        print(f"{key}: {val}")
        else:
            print("Specifications panel not clearly identifiable")

asyncio.run(inspect())
