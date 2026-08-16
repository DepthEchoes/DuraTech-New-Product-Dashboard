"""
深入诊断：搜索选品器中真实的产品卡片 DOM 结构
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/diagnose")
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
        await page.wait_for_timeout(8000)

        # 5. 等待并截图
        await page.screenshot(path=str(OUTPUT_DIR / "01_selected.png"), full_page=False)

        # 6. 滚动到底部
        await page.evaluate("window.scrollTo(0, 1500)")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(OUTPUT_DIR / "02_scrolled.png"), full_page=False)

        # 7. 完整页面截图
        await page.screenshot(path=str(OUTPUT_DIR / "03_full.png"), full_page=True)

        # 8. 详细分析 DOM 结构
        print("\n[5] 分析 DOM 结构...")
        analysis = await page.evaluate("""() => {
            // 查找所有包含 ASIN (B0xxxxx) 的元素
            const asinRe = /B0[A-Z0-9]{8,9}/;
            const allElements = document.querySelectorAll('*');
            const asinElements = [];
            for (const el of allElements) {
                const text = el.innerText || '';
                if (asinRe.test(text) && el.children.length < 30) {
                    asinElements.push({
                        tag: el.tagName,
                        className: (el.className || '').toString().substring(0, 100),
                        id: el.id,
                        childCount: el.children.length,
                        textPreview: text.substring(0, 200).replace(/\\n/g, ' | '),
                    });
                }
            }

            // 查找 .product-card 或类似类
            const productLikeSelectors = [
                '[class*="product"]',
                '[class*="card"]',
                '[class*="item"]',
                '[class*="goods"]',
                '[class*="listing"]',
                '[class*="result"]',
            ];
            const candidates = [];
            for (const sel of productLikeSelectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const cls = (el.className || '').toString();
                    // 只保留容器级别
                    if (el.children.length > 1 && el.children.length < 20) {
                        candidates.push({
                            selector: sel,
                            tag: el.tagName,
                            className: cls.substring(0, 80),
                            childCount: el.children.length,
                            hasAsin: asinRe.test(el.innerText || '')
                        });
                    }
                }
            }

            return {
                asinElementsCount: asinElements.length,
                asinElements: asinElements.slice(0, 10),
                candidates: candidates.slice(0, 20),
            };
        }""")
        print(json.dumps(analysis, ensure_ascii=False, indent=2))

        # 9. 抓取第一个 ASIN 元素的完整HTML
        if analysis['asinElements']:
            target = analysis['asinElements'][0]
            print(f"\n[6] 第一个 ASIN 元素: {target['tag']} class='{target['className']}'")
            first_html = await page.evaluate("""(selector) => {
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    const text = el.innerText || '';
                    if (/B0[A-Z0-9]{8,9}/.test(text) && el.children.length < 30) {
                        return el.outerHTML.substring(0, 3000);
                    }
                }
                return 'not found';
            }""", target.get('className', ''))
            (OUTPUT_DIR / "first_card.html").write_text(first_html)
            print(f"  HTML 长度: {len(first_html)}")

        # 10. 直接用 querySelectorAll 试试
        print("\n[7] 尝试所有可能的容器选择器...")
        selectors_to_try = [
            '.product-card',
            '.card',
            '.item',
            '.result-item',
            '.goods-item',
            '.list-item',
            '[class*="product"]',
            '[class*="result"]',
            '.table-card',
            '.search-result-item',
        ]
        for sel in selectors_to_try:
            try:
                count = await page.locator(sel).count()
                if count > 0:
                    print(f"  {sel}: {count} 个元素")
            except Exception as e:
                pass

        await browser.close()


asyncio.run(main())
