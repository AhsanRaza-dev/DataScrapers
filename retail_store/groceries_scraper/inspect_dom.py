import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def get_html():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = context.pages[0]
        for p in context.pages:
            if "costco.com" in p.url:
                page = p
                break
                
        print(f"URL: {page.url}")
        
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for the product list container
        grid = soup.find(attrs={"data-testid": "Grid"})
        if not grid:
            print("No grid found")
            return
            
        print("Found Grid! First 2000 chars:")
        print(str(grid)[:2000])

asyncio.run(get_html())
