"""
DuraTech 周度采集入口
封装 collector.py，依次采集新品池和爆品池。
用法: python3 weekly_collect.py [cookies.json路径] [--max-pages N]
"""
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from config import OUTPUT_DIR, SESSIONS_DIR


def ensure_cookies(cookie_path):
    """确保 cookies.json 在 sessions/ 目录下"""
    src = Path(cookie_path)
    if not src.exists():
        print(f"[ERROR] Cookie 文件不存在: {cookie_path}")
        sys.exit(1)

    dest = Path(SESSIONS_DIR) / "cookies.json"
    data = json.loads(src.read_text())
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[OK] Cookie 已保存: {dest}")


def run_weekly(cookie_path, max_pages=20):
    """执行周度采集：新品 + 爆品"""
    ensure_cookies(cookie_path)

    import collector

    date_str = datetime.now().strftime("%Y%m%d")
    results = {}

    for collect_type, label in [("new", "新品"), ("hot", "爆品")]:
        print(f"\n{'='*50}")
        print(f"  🚀 开始采集: {label}池")
        print(f"{'='*50}")
        out = collector.run(collect_type, max_pages)
        results[collect_type] = out
        print(f"[OK] {label}池完成: {out}")

    # 汇总
    print(f"\n{'='*50}")
    print("  ✅ 周度采集完成!")
    for ct, path in results.items():
        label = "新品" if ct == "new" else "爆品"
        raw = json.loads(Path(path).read_text())
        total = sum(len(v) for v in raw.values()) if isinstance(raw, dict) else len(raw)
        print(f"     {label}: {total} 条 → {path}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DuraTech 周度采集")
    parser.add_argument("cookie", nargs="?", default=str(SCRIPT_DIR / "cookies.json"),
                        help="Cookie JSON 文件路径 (EditThisCookie 格式)")
    parser.add_argument("--max-pages", "-p", type=int, default=20,
                        help="每个类目最大翻页数")
    args = parser.parse_args()
    run_weekly(args.cookie, args.max_pages)
