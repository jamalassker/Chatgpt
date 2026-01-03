import asyncio
from playwright.async_api import async_playwright
from fastapi import FastAPI
import uvicorn
import os

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "API is online", "status": "running"}


async def scrape_leads(niche: str, location: str):
    async with async_playwright() as p:
        # Launch with no-sandbox (required for Linux/Railway)
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_context().new_page()
        
        search_url = f"https://www.yellowpages.com/search?search_terms={niche}&geo_location_terms={location}"
        
        try:
            # Added timeout and wait_until to ensure data loads
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            
            leads = []
            # Wait for at least one result to appear
            await page.wait_for_selector(".result", timeout=10000)
            elements = await page.query_selector_all(".result")
            
            for el in elements[:15]: 
                name = await el.query_selector(".business-name")
                phone = await el.query_selector(".phones")
                if name and phone:
                    leads.append({
                        "name": await name.inner_text(),
                        "phone": await phone.inner_text()
                    })
            return leads
        except Exception as e:
            return [{"error": str(e)}]
        finally:
            await browser.close()

@app.get("/get-leads")
async def get_leads_api(niche: str, location: str):
    data = await scrape_leads(niche, location)
    return {"status": "success", "count": len(data), "data": data}

if __name__ == "__main__":
    # Railway provides a 'PORT' environment variable automatically
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
