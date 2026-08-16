"""
专门测试 v2 选产品页面
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
        await context.add_cookies(cookies)
        page = await context.new_page()

        # 先访问主页建立会话
        print("[0] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(3000)
        print(f"    主页: {page.url}")

        # 测试 v2 选产品页面
        print("\n[1] 访问 v2 选产品页面...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=30000)
        await page.wait_for_timeout(5000)
        print(f"    URL: {page.url}")
        print(f"    标题: {await page.title()}")
        await page.screenshot(path=str(OUTPUT_DIR / "v2_product_research.png"), full_page=False)

        # 等待页面加载
        await page.wait_for_timeout(5000)
        await page.screenshot(path=str(OUTPUT_DIR / "v2_product_research_loaded.png"), full_page=False)

        # 获取页面文本
        body_text = await page.evaluate("() => document.body.innerText.substring(0, 2000)")
        print(f"\n页面文本片段:\n{body_text[:1000]}")

        # 提取关键元素
        structure = await page.evaluate("""() => {
            const result = {
                nav: [],
                inputs: [],
                selects: [],
                buttons: [],
                tables: [],
                pagination: [],
                tabs: []
            };
            // 顶部导航
            document.querySelectorAll('nav a, .nav-item, .menu-item, [class*="nav"] a').forEach((a, i) => {
                if (i < 20 && a.innerText.trim()) {
                    result.nav.push({text: a.innerText.trim().substring(0, 30), href: a.href});
                }
            });
            // input
            document.querySelectorAll('input').forEach((el, i) => {
                if (i < 20) result.inputs.push({
                    type: el.type, placeholder: el.placeholder,
                    className: (el.className || '').substring(0, 80), name: el.name
                });
            });
            // select
            document.querySelectorAll('select').forEach((el, i) => {
                if (i < 20) result.selects.push({
                    className: (el.className || '').substring(0, 80),
                    options: Array.from(el.options).slice(0, 5).map(o => o.text)
                });
            });
            // tabs
            document.querySelectorAll('[role="tab"], .tab, [class*="tab-item"]').forEach((el, i) => {
                if (i < 20) result.tabs.push({
                    text: (el.innerText || '').trim().substring(0, 30),
                    className: (el.className || '').substring(0, 80)
                });
            });
            // 表格
            document.querySelectorAll('table').forEach((el, i) => {
                if (i < 5) result.tables.push({
                    className: (el.className || '').substring(0, 100),
                    rows: el.querySelectorAll('tr').length
                });
            });
            // 分页
            document.querySelectorAll('[class*="pagination"], [class*="page"]').forEach(el => {
                result.pagination.push({
                    text: (el.innerText || '').substring(0, 50),
                    className: (el.className || '').substring(0, 80)
                });
            });
            return result;
        }""")

        print("\n[2] 页面结构:")
        print(json.dumps(structure, ensure_ascii=False, indent=2))

        # 保存完整 HTML
        full_html = await page.content()
        (OUTPUT_DIR / "v2_product_research.html").write_text(full_html)
        print(f"\n[3] 完整HTML已保存 ({len(full_html)} 字符)")

        await browser.close()


asyncio.run(main())
