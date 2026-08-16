"""
先在主页停留 5秒 让 JS 执行，然后导航
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/explore")


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

        # 使用 Playwright add_cookies
        pw_cookies = []
        for c in cookies:
            pw_c = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
            }
            # Playwright 不允许 sameSite=unspecified, 设为 None
            pw_c["sameSite"] = "None"
            if c.get("httpOnly"):
                pw_c["httpOnly"] = True
            if c.get("secure"):
                pw_c["secure"] = True
            pw_cookies.append(pw_c)
        await context.add_cookies(pw_cookies)

        page = await context.new_page()

        # 第1步：先访问主页
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)  # 等 JS 执行

        # 第2步：再访问中文首页
        print("[2] 访问中文首页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(3000)

        # 检查登录态
        is_logged_in = await page.evaluate("""() => {
            return !document.body.innerText.includes('未登录');
        }""")
        print(f"    是否登录: {is_logged_in}")
        await page.screenshot(path=str(OUTPUT_DIR / "home_check.png"))

        # 第3步：访问 v2 选产品
        print("\n[3] 访问 v2 选产品...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(10000)
        print(f"    URL: {page.url}")

        if 'login' in page.url.lower():
            print("    [FAIL] 仍跳到登录页")
            # 再次尝试用浏览历史
            await page.go_back()
            await page.wait_for_timeout(3000)
            print(f"    go_back URL: {page.url}")
        else:
            print("    [OK] 进入选品器")

        # 第4步：尝试在 URL 上带 callback
        print("\n[4] 访问 v2 选产品（无 callback）...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(10000)
        print(f"    URL: {page.url}")
        await page.screenshot(path=str(OUTPUT_DIR / "retry_v2.png"), full_page=False)

        await browser.close()


asyncio.run(main())
