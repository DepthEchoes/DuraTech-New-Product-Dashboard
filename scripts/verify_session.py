"""
用保存的 Cookie 访问卖家精灵选品器，验证登录态并探索页面结构
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

        # 1. 先访问主页建立会话
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(3000)
        print(f"    主页URL: {page.url}")
        print(f"    主页标题: {await page.title()}")

        # 2. 访问选品器页面
        print("\n[2] 访问选品器...")
        await page.goto("https://www.sellersprite.com/v3/product-research", timeout=60000)
        await page.wait_for_timeout(8000)

        current_url = page.url
        title = await page.title()
        print(f"    URL: {current_url}")
        print(f"    标题: {title}")

        if 'login' in current_url.lower():
            print("[FAIL] Cookie 已过期，需要重新登录")
            await page.screenshot(path=str(OUTPUT_DIR / "cookie_failed.png"))
            await browser.close()
            return

        print("[OK] 登录态有效！")
        await page.screenshot(path=str(OUTPUT_DIR / "research_loaded.png"), full_page=False)

        # 2. 获取页面所有文本，分析结构
        print("\n[2] 分析页面结构...")
        body_text = await page.evaluate("""() => {
            return document.body.innerText.substring(0, 3000);
        }""")
        print(f"    页面文本片段 (前3000字符):\n{body_text[:1500]}...")

        # 3. 探索关键元素
        print("\n[3] 查找关键交互元素...")
        elements = await page.evaluate("""() => {
            const result = {
                tabs: [],
                selects: [],
                buttons: [],
                inputs: [],
                tables: [],
                pagination: []
            };

            // 查找类目选择器
            document.querySelectorAll('[class*="category"], [class*="Category"], [class*="cate"], [placeholder*="类目"], [placeholder*="分类"]').forEach(el => {
                result.selects.push({
                    tag: el.tagName,
                    text: (el.innerText || '').substring(0, 60),
                    className: (el.className || '').substring(0, 100),
                    placeholder: el.placeholder || ''
                });
            });

            // 查找所有 input
            document.querySelectorAll('input').forEach((el, i) => {
                if (i < 15) result.inputs.push({
                    type: el.type, name: el.name, placeholder: el.placeholder,
                    className: (el.className || '').substring(0, 80)
                });
            });

            // 查找所有 select
            document.querySelectorAll('select, [class*="el-select"]').forEach((el, i) => {
                if (i < 15) result.selects.push({
                    tag: el.tagName,
                    text: (el.innerText || '').substring(0, 50),
                    className: (el.className || '').substring(0, 80)
                });
            });

            // 查找表格
            document.querySelectorAll('table, [class*="table"], [class*="Table"]').forEach((el, i) => {
                if (i < 3) result.tables.push({
                    tag: el.tagName,
                    className: (el.className || '').substring(0, 100),
                    rows: el.querySelectorAll('tr').length
                });
            });

            // 查找按钮
            document.querySelectorAll('button').forEach((el, i) => {
                if (i < 20) result.buttons.push({
                    text: (el.innerText || '').substring(0, 40),
                    className: (el.className || '').substring(0, 80)
                });
            });

            // 查找分页
            document.querySelectorAll('[class*="pagination"], [class*="page"], [class*="Pagination"]').forEach(el => {
                result.pagination.push({
                    text: (el.innerText || '').substring(0, 50),
                    className: (el.className || '').substring(0, 100)
                });
            });

            return result;
        }""")
        print(json.dumps(elements, ensure_ascii=False, indent=2))

        # 4. 保存完整HTML用于分析
        full_html = await page.content()
        (OUTPUT_DIR / "research_full.html").write_text(full_html)
        print(f"\n[4] 完整HTML已保存 ({len(full_html)} 字符)")

        # 5. 查找产品列表数据
        print("\n[5] 查找产品数据...")
        data_info = await page.evaluate("""() => {
            const result = {};
            // 尝试找到产品行
            const rows = document.querySelectorAll('tr[class*="row"], .product-item, [class*="product"], .el-table__row');
            result.totalRows = rows.length;

            // 检查是否有 Vue 数据
            if (window.__INITIAL_STATE__) {
                result.hasInitialState = true;
                result.initialStateKeys = Object.keys(window.__INITIAL_STATE__);
            }

            // 检查网络请求API
            result.url = window.location.href;
            result.pathname = window.location.pathname;

            return result;
        }""")
        print(json.dumps(data_info, ensure_ascii=False, indent=2))

        await browser.close()
        print("\n[完成] 选品器页面探索完成")


asyncio.run(main())
