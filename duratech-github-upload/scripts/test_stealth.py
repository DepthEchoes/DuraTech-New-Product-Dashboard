"""
增强隐身浏览器 - 反检测
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    cookies = json.loads(Path("/workspace/sellersprite-automation/sessions/cookies.json").read_text())

    async with async_playwright() as p:
        # 使用 Chromium 持久化上下文
        browser = await p.chromium.launch_persistent_context(
            user_data_dir="/tmp/playwright-profile",
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-web-security',
                '--window-size=1920,1080',
                '--lang=zh-CN',
            ],
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            bypass_csp=True,
            ignore_https_errors=True,
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        # 先访问主页建立 origin
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(3000)

        # 通过 CDP 设置 cookies
        cdp = await page.context.new_cdp_session(page)
        for c in cookies:
            try:
                await cdp.send("Network.setCookie", {
                    "name": c["name"], "value": c["value"],
                    "domain": c["domain"], "path": c.get("path", "/"),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                    "sameSite": "None",
                })
            except:
                pass

        # 重新加载主页激活 session
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)

        # 现在访问选品器
        print("[1] 访问 v2 选品器...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)
        print(f"    URL: {page.url}")
        print(f"    login? {'login' in page.url.lower()}")

        await browser.close()

asyncio.run(main())
