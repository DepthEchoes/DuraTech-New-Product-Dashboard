"""
新 Cookie 测试 - 逐步查看页面状态
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/new_cookie_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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

        # Step 1: 访问主页
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)
        print(f"    URL: {page.url}")
        print(f"    标题: {await page.title()}")
        await page.screenshot(path=str(OUTPUT_DIR / "01_home.png"))

        # Step 2: 访问 v2 选品器
        print("\n[2] 访问 v2 选品器...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(10000)
        print(f"    URL: {page.url}")
        print(f"    标题: {await page.title()}")
        await page.screenshot(path=str(OUTPUT_DIR / "02_v2.png"))

        # Step 3: 查看 body 文本
        body = await page.evaluate("() => document.body.innerText.substring(0, 2000)")
        print(f"\n    Body 片段: {body[:500]}...")
        await page.screenshot(path=str(OUTPUT_DIR / "03_v2_scroll.png"), full_page=True)

        # Step 4: 查找"汽车用品"文本
        has_auto = await page.locator('text="汽车用品"').count()
        print(f"\n    '汽车用品' 出现次数: {has_auto}")

        # Step 5: 查找所有可能的类目文本
        cats = await page.evaluate("""() => {
            const texts = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.children.length === 0 && el.innerText.trim() === '汽车用品') {
                    texts.push({tag: el.tagName, className: (el.className||'').toString().substring(0,80)});
                }
            });
            return texts.slice(0, 10);
        }""")
        print(f"    '汽车用品' 元素: {json.dumps(cats, ensure_ascii=False)}")

        await browser.close()


asyncio.run(main())
