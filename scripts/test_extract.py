"""
直接测试 JS 提取代码
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/test_extract")
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

        # 完整流程
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)

        print("[2] 访问选品器...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)

        print("[3] 选类目...")
        await page.locator('text="汽车用品"').first.click()
        await page.wait_for_timeout(2000)

        print("[4] 选模式...")
        await page.locator('text="销量飙升榜"').first.click()
        await page.wait_for_timeout(10000)

        await page.evaluate("window.scrollTo(0, 1500)")
        await page.wait_for_timeout(2000)

        # 测试 JS 代码
        print("\n[5] 测试 JS 提取...")
        result = await page.evaluate("""() => {
            const cards = document.querySelectorAll('.content-grid-product-box');
            return {
                count: cards.length,
                first: cards.length > 0 ? cards[0].outerHTML.substring(0, 1500) : 'none'
            };
        }""")
        print(f"  找到 {result['count']} 个卡片")
        print(f"  第一个: {result['first'][:300]}...")

        # 测试简化提取
        print("\n[6] 简化版提取...")
        simple = await page.evaluate("""() => {
            const cards = document.querySelectorAll('.content-grid-product-box');
            const results = [];
            for (const card of cards) {
                const asinEl = card.querySelector('.mr-1.text-muted.text-truncate');
                const asin = asinEl ? asinEl.innerText.trim() : '';
                if (asin) {
                    results.push({asin, text: card.innerText.substring(0, 200)});
                }
            }
            return results;
        }""")
        print(f"  找到 {len(simple)} 个 ASIN")
        for i, s in enumerate(simple[:3]):
            print(f"  [{i}] {s['asin']}: {s['text'][:150]}")

        await browser.close()


asyncio.run(main())
