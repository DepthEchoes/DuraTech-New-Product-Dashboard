"""
卖家精灵登录测试 (Playwright版本)
自动填入账号密码，需要手动输入验证码
"""
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/workspace/sellersprite-automation/logs/login_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def test_login(username, password, headed=False):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not headed,
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

        print("[1] 打开登录页...")
        await page.goto("https://www.sellersprite.com/cn/w/user/login", timeout=30000)
        await page.wait_for_timeout(2000)

        # 填入账号
        print(f"[2] 填入账号: {username}")
        # 第一个可见的 email 输入框
        await page.locator('input[name="email"]').first.fill(username)

        # 填入密码 - 第一个 password 输入框
        print(f"[3] 填入密码...")
        # 切换到密码登录 tab (如果不是默认)
        try:
            password_tab = page.locator('a:has-text("密码登录")')
            if await password_tab.is_visible(timeout=2000):
                await password_tab.click()
                await page.wait_for_timeout(1000)
        except:
            pass

        await page.locator('input[name="password"]').first.fill(password)

        # 截图供用户确认
        await page.screenshot(path=str(OUTPUT_DIR / "01_filled.png"), full_page=False)
        print(f"[4] 已填入账号密码，截图: {OUTPUT_DIR / '01_filled.png'}")

        # 尝试自动点击登录
        print("[5] 准备点击登录按钮...")
        login_btn = page.locator('button.login-btn').first
        if headed:
            print("    Headed 模式，请手动点击'立即登录'按钮")
            print("    如果需要验证码，请在浏览器中完成")
            print("    登录完成后，请输入任意字符继续...")
            input()

        else:
            # Headless 模式 - 直接点击，看是否需要验证码
            await login_btn.click()
            print("[6] 已点击登录按钮，等待响应...")
            await page.wait_for_timeout(5000)
            await page.screenshot(path=str(OUTPUT_DIR / "02_after_click.png"), full_page=False)

            # 检查当前状态
            current_url = page.url
            print(f"    当前URL: {current_url}")
            print(f"    页面标题: {await page.title()}")

            if 'login' in current_url.lower():
                print("[WARN] 仍在登录页面，可能需要验证码")
            else:
                print("[OK] 登录成功或已跳转到其他页面")

        # 保存 cookies
        cookies = await context.cookies()
        cookies_path = OUTPUT_DIR / "cookies.json"
        import json
        cookies_path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
        print(f"[7] Cookies 已保存到: {cookies_path} (共 {len(cookies)} 个)")

        await browser.close()
        return cookies


async def load_session_and_check(cookie_file):
    """加载保存的 cookies 并访问选品器验证"""
    import json
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--lang=zh-CN']
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
        )

        # 加载 cookies
        cookies = json.loads(Path(cookie_file).read_text())
        await context.add_cookies(cookies)
        print(f"已加载 {len(cookies)} 个 cookies")

        page = await context.new_page()
        print("[1] 访问选品器页面...")
        await page.goto("https://www.sellersprite.com/v3/product-research", timeout=30000)
        await page.wait_for_timeout(5000)
        await page.screenshot(path=str(OUTPUT_DIR / "03_research_page.png"), full_page=False)
        print(f"    URL: {page.url}")
        print(f"    标题: {await page.title()}")

        if 'login' in page.url.lower():
            print("[FAIL] Cookie 已失效，仍在登录页")
        else:
            print("[OK] 登录状态有效")

        # 探索选品器页面结构
        print("\n[2] 探索选品器页面结构...")
        structure = await page.evaluate("""() => {
            const result = {
                inputs: [],
                selects: [],
                buttons: [],
                tables: [],
                links: []
            };
            document.querySelectorAll('input').forEach(el => {
                result.inputs.push({
                    type: el.type, name: el.name, placeholder: el.placeholder,
                    className: el.className.substring(0, 80), id: el.id
                });
            });
            document.querySelectorAll('select, .el-select, [class*="select"]').forEach((el, i) => {
                if (i < 20) result.selects.push({
                    tag: el.tagName, className: el.className.substring(0, 80),
                    text: el.innerText ? el.innerText.substring(0, 50) : ''
                });
            });
            document.querySelectorAll('button, .el-button').forEach((el, i) => {
                if (i < 20) result.buttons.push({
                    text: el.innerText ? el.innerText.substring(0, 30) : '',
                    className: el.className.substring(0, 80)
                });
            });
            document.querySelectorAll('table, .el-table, [class*="table"]').forEach((el, i) => {
                if (i < 5) result.tables.push({
                    tag: el.tagName, className: el.className.substring(0, 100),
                    rows: el.querySelectorAll('tr').length
                });
            });
            return result;
        }""")
        import json as json_mod
        print(json_mod.dumps(structure, ensure_ascii=False, indent=2))

        await browser.close()


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("用法: python test_login.py <username> <password> [--headed] [cookie_file]")
        print("或: python test_login.py --check <cookie_file>")
        sys.exit(1)

    if sys.argv[1] == '--check':
        cookie_file = sys.argv[2]
        asyncio.run(load_session_and_check(cookie_file))
    else:
        username = sys.argv[1]
        password = sys.argv[2]
        headed = '--headed' in sys.argv
        asyncio.run(test_login(username, password, headed))
