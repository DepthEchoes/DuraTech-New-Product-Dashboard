"""
通过 CDP 直接设置 Cookie，解决 httpOnly 问题
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/explore")
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

        # 先打开主页，建立 origin
        page = await context.new_page()
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(2000)

        # 通过 CDP 设置 Cookie (可以设置 httpOnly)
        cdp = await context.new_cdp_session(page)
        all_set = 0
        for c in cookies:
            cdp_args = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
            }
            # httpOnly 通过 CDP 设置
            if c.get("httpOnly"):
                cdp_args["httpOnly"] = True
            if c.get("secure"):
                cdp_args["secure"] = True
            # 处理 sameSite
            same_site = c.get("sameSite", "unspecified")
            if same_site == "unspecified":
                cdp_args["sameSite"] = "Lax"  # Playwright 不支持 None/Unspecified
            elif same_site in ["Lax", "Strict", "None"]:
                cdp_args["sameSite"] = same_site

            try:
                await cdp.send("Network.setCookie", cdp_args)
                all_set += 1
            except Exception as e:
                print(f"设置失败 {c['name']}: {e}")

        print(f"通过 CDP 设置了 {all_set} 个 cookies")

        # 重新加载页面测试
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)
        current_url = page.url
        title = await page.title()
        print(f"\nURL: {current_url}")
        print(f"标题: {title}")
        await page.screenshot(path=str(OUTPUT_DIR / "cdp_login.png"), full_page=False)
        await page.wait_for_timeout(3000)
        await page.screenshot(path=str(OUTPUT_DIR / "cdp_login_loaded.png"), full_page=False)

        # 检查登录状态
        if 'login' in current_url.lower():
            print("[FAIL] 仍重定向到登录页")
        else:
            print("[OK] 登录态有效")

            # 提取页面文本看是否已登录
            body_text = await page.evaluate("() => document.body.innerText.substring(0, 1500)")
            print(f"\n页面文本:\n{body_text[:800]}")

            # 找到"已登录"的标识
            user_info = await page.evaluate("""() => {
                const u = document.querySelector('.user-name, .nickname, [class*="user-name"]');
                if (u) return u.innerText;
                // 检查导航中的用户信息
                const allText = document.body.innerText;
                if (allText.includes('DuraT')) return 'DuraT found';
                if (allText.includes('未登录')) return '未登录';
                return 'unknown';
            }""")
            print(f"用户标识: {user_info}")

        await browser.close()


asyncio.run(main())
