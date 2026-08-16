"""
通过网络拦截方式获取卖家精灵选品器 API 请求
避免页面 DOM 操作被反爬检测
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/network")
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

        # 收集 API 请求
        api_requests = []

        async def capture_api(response):
            url = response.url
            if 'api' in url or 'rank' in url or 'graphql' in url:
                try:
                    body = await response.text()
                    api_requests.append({
                        'url': url,
                        'status': response.status,
                        'body_preview': body[:500] if len(body) > 500 else body,
                    })
                except:
                    pass

        page.on('response', capture_api)

        # 访问主页
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)

        # 访问 v2 选品器
        print("[2] 访问 v2 选品器...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)
        print(f"    URL: {page.url}")

        if 'login' in page.url.lower():
            print("    [FAIL] 重定向到登录页")
            await browser.close()
            return

        print("    [OK] 进入选品器")

        # 选类目
        print("[3] 选类目 Automotive...")
        await page.locator('text="汽车用品"').first.click()
        await page.wait_for_timeout(2000)

        # 选模式
        print("[4] 选模式 销量飙升榜...")
        await page.locator('text="销量飙升榜"').first.click()
        await page.wait_for_timeout(10000)

        # 等待 API 请求
        await page.wait_for_timeout(5000)

        # 输出捕获的 API 请求
        print(f"\n[5] 捕获到 {len(api_requests)} 个 API 请求:")
        for i, req in enumerate(api_requests):
            print(f"\n  [{i}] {req['url']} (status={req['status']})")
            print(f"      {req['body_preview'][:300]}")

        # 保存所有 API 请求
        (OUTPUT_DIR / "api_requests.json").write_text(json.dumps(api_requests, ensure_ascii=False, indent=2))

        await browser.close()


asyncio.run(main())
