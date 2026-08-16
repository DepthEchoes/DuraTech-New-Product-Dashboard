"""
极简测试：直接 goto v2，看是否能成功
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

        # 直接访问 v2 选品器 (不先访问主页)
        print("[1] 直接访问 v2/product-research...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(10000)
        print(f"    URL: {page.url}")
        print(f"    标题: {await page.title()}")

        if 'login' in page.url.lower():
            print("    [FAIL] 重定向到登录页")
        else:
            print("    [OK] 进入选品器")
            # 检查产品数量
            count = await page.locator('.content-grid-product-box').count()
            print(f"    产品数: {count}")

        # 先访问主页再访问 v2
        print("\n[2] 先访问主页再访问 v2...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(10000)
        print(f"    URL: {page.url}")
        if 'login' not in page.url.lower():
            count = await page.locator('.content-grid-product-box').count()
            print(f"    产品数: {count}")

        # 试 cn/v2
        print("\n[3] 试 cn/v2/product-research...")
        await page.goto("https://www.sellersprite.com/cn/v2/product-research", timeout=60000)
        await page.wait_for_timeout(10000)
        print(f"    URL: {page.url}")

        # 试 w/v2
        print("\n[4] 试 w/v2/product-research...")
        await page.goto("https://www.sellersprite.com/w/v2/product-research", timeout=60000)
        await page.wait_for_timeout(10000)
        print(f"    URL: {page.url}")

        await browser.close()


asyncio.run(main())
