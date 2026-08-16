"""
测试多个可能的选品器 URL
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/explore")

URLS_TO_TEST = [
    ("https://www.sellersprite.com/v3/product-research", "选品器v3"),
    ("https://www.sellersprite.com/v2/product-research", "选品器v2"),
    ("https://www.sellersprite.com/v3/product-research?site=1", "选品器v3(US)"),
    ("https://www.sellersprite.com/v2/product-research?site=1", "选品器v2(US)"),
    ("https://www.sellersprite.com/cn/v3/product-research", "选品器v3(cn)"),
    ("https://www.sellersprite.com/cn/v2/product-research", "选品器v2(cn)"),
    ("https://www.sellersprite.com/v3/keyword-research", "关键词选品"),
    ("https://www.sellersprite.com/v2/market-research", "选市场"),
    ("https://www.sellersprite.com/v3/competitor-lookup", "查竞品"),
    ("https://www.sellersprite.com/cn/w/user/index", "用户首页"),
    ("https://www.sellersprite.com/v2/product-tracking", "产品监控"),
]


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
        await context.add_cookies(cookies)
        page = await context.new_page()

        # 先访问主页
        print("[0] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(2000)
        home_url = page.url
        print(f"    主页URL: {home_url}")
        print(f"    主页标题: {await page.title()}")

        # 检查登录状态
        login_status = await page.evaluate("""() => {
            const userEl = document.querySelector('.user-name, .user-info, .nickname, [class*="user"]');
            return userEl ? userEl.innerText : 'not found';
        }""")
        print(f"    用户信息: {login_status}")

        results = []
        for url, name in URLS_TO_TEST:
            print(f"\n[测试] {name}: {url}")
            try:
                await page.goto(url, timeout=30000)
                await page.wait_for_timeout(3000)
                final_url = page.url
                title = await page.title()
                is_50x = '50x' in final_url or '50x' in title

                status = "50x错误" if is_50x else f"OK({len(await page.content())}字节)"
                print(f"    -> {status} | URL: {final_url} | 标题: {title[:60]}")

                results.append({
                    "name": name,
                    "url": url,
                    "final_url": final_url,
                    "title": title[:80],
                    "status": status,
                })

                if not is_50x:
                    await page.screenshot(path=str(OUTPUT_DIR / f"test_{name.replace(' ', '_')}.png"))

            except Exception as e:
                print(f"    -> 错误: {e}")
                results.append({"name": name, "url": url, "error": str(e)})

        # 汇总
        print("\n\n" + "="*60)
        print("测试结果汇总:")
        print("="*60)
        for r in results:
            status = r.get('status', r.get('error', 'unknown'))
            print(f"  [{status}] {r['name']}: {r['url']}")

        await browser.close()


asyncio.run(main())
