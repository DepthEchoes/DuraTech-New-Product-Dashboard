"""
使用 StorageState 方式导入 Cookie 测试
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    cookies = json.loads(Path("/workspace/sellersprite-automation/sessions/cookies.json").read_text())

    # 构建 storageState
    origins = {}
    for c in cookies:
        domain = c["domain"].lstrip('.')
        origin = f"https://{domain}"
        if origin not in origins:
            origins[origin] = []

        cookie_entry = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
            "sameSite": "None" if c.get("sameSite") == "unspecified" else c.get("sameSite", "None"),
        }
        if not c.get("session"):
            cookie_entry["expires"] = c.get("expirationDate", -1)
        origins[origin].append(cookie_entry)

    storage_state = {"cookies": cookies, "origins": []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--lang=zh-CN', '--window-size=1920,1080']
        )

        # 方法1: 直接 add_cookies
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
        )
        pw_cookies = []
        for c in cookies:
            pw_c = {
                "name": c["name"], "value": c["value"], "domain": c["domain"],
                "path": c.get("path", "/"), "sameSite": "None",
            }
            if c.get("httpOnly"): pw_c["httpOnly"] = True
            if c.get("secure"): pw_c["secure"] = True
            pw_cookies.append(pw_c)
        await context.add_cookies(pw_cookies)

        page = await context.new_page()
        print("[方法1: add_cookies]")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)
        print(f"  URL: {page.url}")
        print(f"  login? {'login' in page.url.lower()}")

        await browser.close()

asyncio.run(main())
