"""
最简流程：模拟 test_extract.py 成功路径
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    cookies = json.loads(Path("/workspace/sellersprite-automation/sessions/cookies.json").read_text())

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--lang=zh-CN', '--window-size=1920,1080']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
        )
        pw_cookies = []
        for c in cookies:
            pw_c = {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/"), "sameSite": "None"}
            if c.get("httpOnly"): pw_c["httpOnly"] = True
            if c.get("secure"): pw_c["secure"] = True
            pw_cookies.append(pw_c)
        await context.add_cookies(pw_cookies)
        page = await context.new_page()

        # 严格模拟 test_extract.py
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)

        print("[2] 访问选品器...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)

        print("[3] 选类目 Automotive...")
        await page.locator('text="汽车用品"').first.click()
        await page.wait_for_timeout(2000)

        print("[4] 选模式 销量飙升榜...")
        await page.locator('text="销量飙升榜"').first.click()
        await page.wait_for_timeout(10000)

        # 滚动到产品区
        await page.evaluate("window.scrollTo(0, 1500)")
        await page.wait_for_timeout(2000)

        # 提取
        print("[5] 提取产品...")
        result = await page.evaluate("""() => {
            const cards = document.querySelectorAll('.content-grid-product-box');
            return cards.length;
        }""")
        print(f"    产品数: {result}")

        await browser.close()


asyncio.run(main())
