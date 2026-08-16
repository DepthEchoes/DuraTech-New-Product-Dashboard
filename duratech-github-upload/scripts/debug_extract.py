"""
调试模式：保存 HTML 来看看到底什么情况
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/debug")
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

        # 1. 访问主页
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)

        # 2. 访问选品器
        print("[2] 访问选品器...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)

        # 3. 选类目
        print("[3] 选类目 Automotive...")
        await page.locator('text="汽车用品"').first.click()
        await page.wait_for_timeout(2000)

        # 4. 选模式
        print("[4] 选模式 销量飙升榜...")
        await page.locator('text="销量飙升榜"').first.click()
        await page.wait_for_timeout(10000)

        # 5. 滚动到底部
        await page.evaluate("window.scrollTo(0, 1500)")
        await page.wait_for_timeout(2000)

        # 6. 保存完整HTML
        html = await page.content()
        (OUTPUT_DIR / "page.html").write_text(html)
        print(f"  HTML 长度: {len(html)}")
        await page.screenshot(path=str(OUTPUT_DIR / "page.png"), full_page=False)

        # 7. 简单查询
        count = await page.locator('.content-grid-product-box').count()
        print(f"  .content-grid-product-box 数量: {count}")

        count2 = await page.locator('.module-grid-product').count()
        print(f"  .module-grid-product 数量: {count2}")

        # 8. 看 body 文本
        body_text = await page.evaluate("() => document.body.innerText.substring(2000, 4000)")
        print(f"\nBody 文本片段:\n{body_text}")

        # 9. 看所有 class 包含 product 的元素
        all_classes = await page.evaluate("""() => {
            const all = document.querySelectorAll('[class*="product"]');
            const seen = new Set();
            for (const el of all) {
                seen.add((el.className || '').toString().substring(0, 80));
            }
            return Array.from(seen);
        }""")
        print(f"\n所有 product 相关 class:")
        for c in all_classes:
            print(f"  - {c}")

        await browser.close()


asyncio.run(main())
