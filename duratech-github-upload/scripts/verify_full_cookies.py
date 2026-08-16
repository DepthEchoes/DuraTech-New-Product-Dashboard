"""
用完整 Cookie (含 httpOnly/多 domain) 测试选品器访问
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/explore")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

async def main():
    cookies = json.loads(Path("/workspace/sellersprite-automation/sessions/cookies.json").read_text())

    # 转换为 Playwright 格式
    pw_cookies = []
    for c in cookies:
        pw_c = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
            "sameSite": "None" if c.get("sameSite") == "unspecified" else c.get("sameSite", "None"),
        }
        pw_cookies.append(pw_c)

    print(f"加载 {len(pw_cookies)} 个 cookies")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--lang=zh-CN', '--window-size=1920,1080']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
        )
        await context.add_cookies(pw_cookies)

        page = await context.new_page()

        # 1. 访问主页
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(3000)
        print(f"    URL: {page.url} | 标题: {await page.title()}")

        # 2. 测试 v2 选产品
        print("\n[2] 测试 v2 选产品页面...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)
        current_url = page.url
        title = await page.title()
        print(f"    URL: {current_url}")
        print(f"    标题: {title}")

        if 'login' in current_url.lower():
            print("    [FAIL] 被重定向到登录页")
            await page.screenshot(path=str(OUTPUT_DIR / "v2_fail.png"))
        else:
            print("    [OK] 登录态有效！")
            await page.screenshot(path=str(OUTPUT_DIR / "v2_success.png"), full_page=False)
            await page.wait_for_timeout(3000)
            await page.screenshot(path=str(OUTPUT_DIR / "v2_success_loaded.png"), full_page=False)

            # 分析页面结构
            body_text = await page.evaluate("() => document.body.innerText.substring(0, 2000)")
            print(f"\n页面文本片段:\n{body_text[:800]}")

            # 关键元素
            structure = await page.evaluate("""() => {
                const r = {selects:[], inputs:[], tables:[], buttons:[]};
                document.querySelectorAll('input, select').forEach((el,i) => {
                    if(i<20) r.inputs.push({
                        tag: el.tagName,
                        type: el.type||'',
                        placeholder: el.placeholder||'',
                        className: (el.className||'').substring(0,80)
                    });
                });
                document.querySelectorAll('table').forEach((el,i) => {
                    if(i<5) r.tables.push({
                        rows: el.querySelectorAll('tr').length,
                        className: (el.className||'').substring(0,100)
                    });
                });
                document.querySelectorAll('button').forEach((el,i) => {
                    if(i<10) r.buttons.push({
                        text: (el.innerText||'').trim().substring(0,30),
                        className: (el.className||'').substring(0,80)
                    });
                });
                return r;
            }""")
            print(f"\n页面结构: {json.dumps(structure, ensure_ascii=False, indent=2)}")

            # 保存完整 HTML
            html = await page.content()
            (OUTPUT_DIR / "v2_product_full.html").write_text(html)
            print(f"\nHTML已保存 ({len(html)} 字符)")

        # 3. 测试 v2 选市场
        print("\n[3] 测试 v2 选市场...")
        await page.goto("https://www.sellersprite.com/v2/market-research", timeout=30000)
        await page.wait_for_timeout(5000)
        print(f"    URL: {page.url} | 标题: {await page.title()}")
        await page.screenshot(path=str(OUTPUT_DIR / "v2_market.png"), full_page=False)

        await browser.close()

asyncio.run(main())
