"""
卖家精灵选品器页面结构探索 (Playwright版本)
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/explore")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

async def explore():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--window-size=1920,1080',
                '--lang=zh-CN',
            ]
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
        )
        page = await context.new_page()

        # 1. 打开卖家精灵首页
        print("[1] 打开卖家精灵首页...")
        await page.goto("https://www.sellersprite.com/cn/", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.screenshot(path=str(OUTPUT_DIR / "01_homepage.png"), full_page=False)
        print(f"    当前URL: {page.url}")
        print(f"    页面标题: {await page.title()}")

        # 2. 打开登录页面
        print("\n[2] 打开登录页面...")
        await page.goto("https://www.sellersprite.com/cn/w/user/login", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.screenshot(path=str(OUTPUT_DIR / "02_login_page.png"), full_page=False)
        print(f"    当前URL: {page.url}")
        print(f"    页面标题: {await page.title()}")

        # 提取页面结构
        html = await page.content()
        (OUTPUT_DIR / "02_login_page.html").write_text(html[:10000])
        print(f"    页面HTML长度: {len(html)}")

        # 查找输入框
        inputs = await page.query_selector_all('input')
        print(f"\n    找到 {len(inputs)} 个 input 元素:")
        for i, inp in enumerate(inputs):
            attrs = await inp.evaluate("""el => ({
                type: el.type, name: el.name, placeholder: el.placeholder,
                className: el.className, id: el.id, autocomplete: el.autocomplete
            })""")
            print(f"    Input[{i}]: {json.dumps(attrs, ensure_ascii=False)}")

        # 查找按钮
        btns = await page.query_selector_all('button')
        print(f"\n    找到 {len(btns)} 个 button 元素:")
        for i, btn in enumerate(btns):
            text = await btn.inner_text()
            cls = await btn.get_attribute('class')
            print(f"    Button[{i}]: text='{text[:60]}' class='{cls}'")

        # 查找所有链接
        links = await page.query_selector_all('a')
        print(f"\n    找到 {len(links)} 个链接 (前20个):")
        count = 0
        for a in links:
            href = await a.get_attribute('href') or ''
            text = (await a.inner_text()).strip()
            if href and count < 20:
                print(f"    {text[:40]}: {href[:80]}")
                count += 1

        # 3. 尝试获取页面中所有可交互元素
        print("\n[3] 提取关键页面结构...")
        structure = await page.evaluate("""() => {
            const result = { forms: [], nav: [], main: [] };
            document.querySelectorAll('form').forEach(f => {
                result.forms.push({ action: f.action, method: f.method, className: f.className });
            });
            document.querySelectorAll('nav a, .nav a, .navbar a, .menu a').forEach(a => {
                if (a.href && a.innerText.trim()) result.nav.push({ text: a.innerText.trim().substring(0,30), href: a.href.substring(0,100) });
            });
            return result;
        }""")
        print(json.dumps(structure, ensure_ascii=False, indent=2))

        # 4. 保存 cookie 信息
        cookies = await context.cookies()
        print(f"\n[4] 当前 Cookies ({len(cookies)} 个):")
        for c in cookies:
            print(f"    {c['name']}: domain={c['domain']}, expires={c.get('expires', 'session')}")

        await browser.close()
        print(f"\n[完成] 所有输出已保存到: {OUTPUT_DIR}")

asyncio.run(explore())
