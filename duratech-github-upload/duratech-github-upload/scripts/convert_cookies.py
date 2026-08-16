"""
将 cookie 字符串转为 Playwright 格式并保存
"""
import json
from pathlib import Path

cookie_str = Path("/workspace/sellersprite-automation/sessions/cookie_string.txt").read_text().strip()

cookies = []
for item in cookie_str.split("; "):
    if "=" in item:
        name, _, value = item.partition("=")
        cookies.append({
            "name": name,
            "value": value,
            "domain": ".sellersprite.com",
            "path": "/",
        })

# 保存为 JSON
output = Path("/workspace/sellersprite-automation/sessions/cookies.json")
output.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
print(f"已转换 {len(cookies)} 个 cookies 到 {output}")

# 打印关键 cookies
for c in cookies:
    if c['name'] in ['rank-login-user', 'Sprite-X-Token', 'ecookie', 'current_guest']:
        print(f"  {c['name']}: {c['value'][:50]}...")
