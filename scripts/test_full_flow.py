"""
完整测试：访问选品器 + 选择类目 + 执行筛选 + 抓取数据
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/test_full")
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

        # 1. 访问主页激活 session
        print("[1] 访问主页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(5000)
        await page.screenshot(path=str(OUTPUT_DIR / "01_home.png"))

        # 2. 访问选品器
        print("[2] 访问 v2 选品器...")
        await page.goto("https://www.sellersprite.com/v2/product-research", timeout=60000)
        await page.wait_for_timeout(8000)
        print(f"    URL: {page.url}")
        await page.screenshot(path=str(OUTPUT_DIR / "02_research.png"))
        await page.wait_for_timeout(3000)
        await page.screenshot(path=str(OUTPUT_DIR / "03_research_loaded.png"), full_page=False)

        # 3. 选择站点 = 美国站
        print("[3] 选择站点...")
        try:
            await page.locator('text="美国站(com)"').first.click()
            await page.wait_for_timeout(2000)
            print("    [OK] 已选择美国站")
        except Exception as e:
            print(f"    [WARN] {e}")

        # 4. 选择月份 = 最近30天
        print("[4] 选择月份...")
        try:
            await page.locator('text="最近30天"').first.click()
            await page.wait_for_timeout(2000)
            print("    [OK] 已选择最近30天")
        except Exception as e:
            print(f"    [WARN] {e}")

        # 5. 选 Automotive 类目
        print("[5] 选 Automotive 类目...")
        try:
            await page.locator('text="汽车用品"').first.click()
            await page.wait_for_timeout(2000)
            print("    [OK] 已选择汽车用品")
        except Exception as e:
            print(f"    [WARN] {e}")

        # 6. 选择模式 = 销量飙升榜（新品模式）
        print("[6] 选择模式...")
        try:
            await page.locator('text="销量飙升榜"').first.click()
            await page.wait_for_timeout(2000)
            print("    [OK] 已选择销量飙升榜")
        except Exception as e:
            print(f"    [WARN] {e}")

        await page.screenshot(path=str(OUTPUT_DIR / "04_after_filter.png"), full_page=False)

        # 7. 滚动到下方看是否有"立即查询"按钮
        print("[7] 滚动查找查询按钮...")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(OUTPUT_DIR / "05_scrolled.png"), full_page=False)

        # 8. 查找立即查询按钮
        try:
            query_btn = page.locator('button:has-text("立即查询")').first
            print(f"    找到立即查询按钮: {await query_btn.is_visible()}")
            await query_btn.click()
            print("    [OK] 已点击立即查询")
            await page.wait_for_timeout(8000)
        except Exception as e:
            print(f"    [WARN] {e}")

        await page.screenshot(path=str(OUTPUT_DIR / "06_results.png"), full_page=False)

        # 9. 滚动到表格位置
        await page.evaluate("window.scrollTo(0, 1500)")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(OUTPUT_DIR / "07_table.png"), full_page=False)

        # 10. 抓取表格数据
        print("\n[8] 抓取表格数据...")
        table_data = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table.loose-table');
            if (tables.length === 0) return {error: 'no table'};
            // 取最大的表格
            let mainTable = null;
            let maxRows = 0;
            tables.forEach(t => {
                const rows = t.querySelectorAll('tr').length;
                if (rows > maxRows) { maxRows = rows; mainTable = t; }
            });
            if (!mainTable) return {error: 'no main table'};

            // 提取表头
            const headers = Array.from(mainTable.querySelectorAll('th, thead td')).map(h => h.innerText.trim());
            // 提取数据行
            const rows = mainTable.querySelectorAll('tbody tr, tr');
            const data = [];
            rows.forEach((row, i) => {
                if (i > 50) return;  // 限制行数
                const cells = Array.from(row.querySelectorAll('td')).map(c => c.innerText.trim());
                if (cells.length > 1) data.push(cells);
            });

            return { headers, rowCount: data.length, sample: data.slice(0, 5) };
        }""")
        print(json.dumps(table_data, ensure_ascii=False, indent=2))

        # 保存 HTML
        html = await page.content()
        (OUTPUT_DIR / "results.html").write_text(html)
        print(f"\nHTML已保存 ({len(html)} 字符)")

        await browser.close()


asyncio.run(main())
