"""
DuraTech 周度对比去重
加载本周采集结果，与上周数据对比：
  - 全新 ASIN → 直接进入需求池
  - 已有 ASIN 且本周销量 > 上周销量 → 保留，备注「销量增长 +X%」
  - 已有 ASIN 且本周销量 ≤ 上周销量 → 跳过
输出: output/weekly/new_pool_{date}.json, hot_pool_{date}.json
"""
import sys
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from config import OUTPUT_DIR

WEEKLY_DIR = Path(OUTPUT_DIR) / "weekly"


def load_raw_products(raw_path):
    """加载原始采集数据或需求池数据，返回 {asin: product}"""
    data = json.loads(Path(raw_path).read_text())
    products = {}
    # 兼容两种格式: {cat: [...]} (raw) 或 {"products": [...]} (pool)
    if "products" in data:
        items = data["products"]
        for p in items:
            asin = p.get("asin", "")
            if asin:
                products[asin] = p
    else:
        for cat, items in data.items():
            if isinstance(items, list):
                for p in items:
                    asin = p.get("asin", "")
                    if asin:
                        # 细分类目模式下 key 形如 "一级 > 细分类目"，
                        # 只在产品没有一级类目时才补（不覆盖 collector 设置的 category）
                        base_l1 = cat.split(" > ")[0].strip()
                        if not p.get("category"):
                            p["category"] = base_l1
                        if not p.get("category_l1"):
                            p["category_l1"] = base_l1
                        products[asin] = p
    return products


def find_latest_raw(collect_type):
    """找到 output/ 下最新的 raw_data_{type}_*.json"""
    pattern = f"raw_data_{collect_type}_*.json"
    candidates = sorted(Path(OUTPUT_DIR).glob(pattern), reverse=True)
    return str(candidates[0]) if candidates else None


def find_previous_weekly(collect_type):
    """找到上一周的数据作为对比基线。
    优先级: weekly/{type}_pool_*.json > 合并最近的 raw_data_{type}_*.json
    """
    pattern = f"{collect_type}_pool_*.json"
    candidates = sorted(WEEKLY_DIR.glob(pattern), reverse=True)
    if candidates:
        return str(candidates[0])

    # 回退：合并最近的 raw_data（排除本周的）
    raw_pattern = f"raw_data_{collect_type}_*.json"
    raw_files = sorted(Path(OUTPUT_DIR).glob(raw_pattern))
    if not raw_files:
        return None

    # 找到最新 raw_data 的日期，排除当天
    by_date = defaultdict(list)
    for f in raw_files:
        if f.stat().st_size <= 100:
            continue
        # 从文件名提取日期: raw_data_new_20260713_090426.json
        try:
            date_str = f.stem.split('_')[3][:8]
            by_date[date_str].append(f)
        except (IndexError, ValueError):
            continue

    if not by_date:
        return None

    # 取最近但不是今天的日期
    today = datetime.now().strftime("%Y%m%d")
    dates = sorted([d for d in by_date.keys() if d != today], reverse=True)
    if not dates:
        return None

    prev_date = dates[0]
    prev_files = by_date[prev_date]
    print(f"  [回退] 使用 raw_data {prev_date} 作为对比基线 ({len(prev_files)} 个文件)")

    # 合并所有文件
    merged = {}
    for f in prev_files:
        try:
            data = json.loads(f.read_text())
            if isinstance(data, dict):
                for cat, items in data.items():
                    if isinstance(items, list):
                        for p in items:
                            asin = p.get("asin", "")
                            if asin:
                                p["category"] = cat
                                merged[asin] = p
        except Exception:
            continue
    return merged  # 直接返回合并后的 dict，而非文件路径


def parse_sales(p):
    """安全解析销量为整数"""
    val = p.get("sales", 0)
    try:
        return int(float(str(val).replace(",", "").replace("+", "")))
    except (ValueError, TypeError):
        return 0


def diff_and_filter(this_week_products, last_week_products):
    """
    对比两周数据，返回过滤后的产品列表。
    this_week: {asin: product}
    last_week: {asin: product} 或 None（首次运行）
    """
    kept = []
    stats = {"new": 0, "grew": 0, "skipped_same": 0, "skipped_decline": 0}

    for asin, p in this_week_products.items():
        p["_growth_note"] = ""  # 初始化备注

        if last_week_products is None or asin not in last_week_products:
            # 全新 ASIN
            p["_growth_note"] = "🆕 新上架"
            kept.append(p)
            stats["new"] += 1
        else:
            this_sales = parse_sales(p)
            last_sales = parse_sales(last_week_products[asin])

            if this_sales > last_sales and last_sales > 0:
                growth_pct = round((this_sales - last_sales) / last_sales * 100)
                p["_growth_note"] = f"📈 销量增长 +{growth_pct}% ({last_sales}→{this_sales})"
                kept.append(p)
                stats["grew"] += 1
            elif this_sales > last_sales and last_sales == 0:
                # 上周销量为 0，本周有销量
                p["_growth_note"] = f"📈 新增销量 {this_sales}"
                kept.append(p)
                stats["grew"] += 1
            elif this_sales == last_sales:
                stats["skipped_same"] += 1
            else:
                stats["skipped_decline"] += 1

    return kept, stats


def _parse_date(s):
    """解析上架时间，返回 date 或 None"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def days_since(p):
    d = _parse_date(p.get("available", ""))
    if d is None:
        return None
    return (datetime.now().date() - d).days


def parse_int(v):
    if v is None:
        return 0
    try:
        return int(float(str(v).replace(",", "").replace("+", "").replace("$", "")))
    except (ValueError, TypeError):
        return 0


def classify_product(p):
    """按业务规则将单品归入 新品池 / 爆品池 / 无。
    新品: 上架≤30天 且 近30天销量≥5
    爆品: 上架≥60天 且 月销售额≥2000（≥5000 为头部爆品）
    注：30天与60天互斥，保证两池天然不重叠。
    """
    ds = days_since(p)
    sales = parse_sales(p)
    monthly = parse_int(p.get("monthly_sales"))
    if ds is not None:
        if ds <= 30 and sales >= 5:
            return "new"
        if ds >= 60 and monthly >= 2000:
            return "hot"
        return None
    # 上架日期缺失：按销量兜底归类
    if monthly >= 2000:
        return "hot"
    if sales >= 5:
        return "new"
    return None


def run_diff(raw_new_path=None, raw_hot_path=None):
    """执行周度对比。
    关键修复：新品池/爆品池不再依赖卖家精灵两次请求(minSales=5 vs 2000)是否
    真的过滤——很多情况下两次返回相同产品，导致两池变成同一批。改为合并本周
    new/hot 采集结果后，按产品自身属性(上架时间+销量)归类，保证两池天然不重叠。
    """
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")

    # 自动找到最新的原始采集文件
    if raw_new_path is None:
        raw_new_path = find_latest_raw("new")
    if raw_hot_path is None:
        raw_hot_path = find_latest_raw("hot")

    if not raw_new_path and not raw_hot_path:
        print("[ERROR] 找不到采集数据，请先运行采集")
        return None

    print(f"本周新品数据: {raw_new_path}")
    print(f"本周爆品数据: {raw_hot_path}")

    # 合并本周 new/hot 采集结果（按 ASIN 去重，取并集）
    all_products = {}
    for rp in (raw_new_path, raw_hot_path):
        if rp:
            all_products.update(load_raw_products(rp))
    print(f"本周合并去重后产品: {len(all_products)} 条")

    # 按属性归类到新品池 / 爆品池候选
    new_candidates, hot_candidates = {}, {}
    for asin, p in all_products.items():
        cls = classify_product(p)
        if cls == "new":
            new_candidates[asin] = p
        elif cls == "hot":
            hot_candidates[asin] = p
    print(f"归类 → 新品候选: {len(new_candidates)} 条, 爆品候选: {len(hot_candidates)} 条")

    # 加载上周对比基线（用于周环比去重：仅保留新上架 / 销量增长）
    last_new = find_previous_weekly("new")
    last_hot = find_previous_weekly("hot")
    if isinstance(last_new, str):
        last_new = load_raw_products(last_new)
    if isinstance(last_hot, str):
        last_hot = load_raw_products(last_hot)

    print(f"上周新品基线: {len(last_new) if last_new else '无(首次运行)'} 条")
    print(f"上周爆品基线: {len(last_hot) if last_hot else '无(首次运行)'} 条")

    # 周环比去重
    print("\n--- 新品池对比 ---")
    kept_new, stats_new = diff_and_filter(new_candidates, last_new)
    print(f"  新上架: {stats_new['new']}, 增长: {stats_new['grew']}, "
          f"跳过(持平): {stats_new['skipped_same']}, 跳过(下降): {stats_new['skipped_decline']}")

    print("--- 爆品池对比 ---")
    kept_hot, stats_hot = diff_and_filter(hot_candidates, last_hot)
    print(f"  新上架: {stats_hot['new']}, 增长: {stats_hot['grew']}, "
          f"跳过(持平): {stats_hot['skipped_same']}, 跳过(下降): {stats_hot['skipped_decline']}")

    # 打标签（前端标签列 / 一键导入依赖）
    for p in kept_new:
        p["__label__"] = "潜力新品"
    for p in kept_hot:
        monthly = parse_int(p.get("monthly_sales"))
        p["__label__"] = "头部爆品" if monthly >= 5000 else "标准爆品"

    # 保存本周需求池
    # 格式: {"type": "new_pool"/"hot_pool", "products": [...], "week": "20260720", "stats": {...}}
    new_pool_path = WEEKLY_DIR / f"new_pool_{date_str}.json"
    hot_pool_path = WEEKLY_DIR / f"hot_pool_{date_str}.json"

    new_pool = {
        "type": "new_pool",
        "week": date_str,
        "stats": stats_new,
        "products": kept_new
    }
    hot_pool = {
        "type": "hot_pool",
        "week": date_str,
        "stats": stats_hot,
        "products": kept_hot
    }

    new_pool_path.write_text(json.dumps(new_pool, ensure_ascii=False, indent=2))
    hot_pool_path.write_text(json.dumps(hot_pool, ensure_ascii=False, indent=2))

    print(f"\n✅ 需求池已保存:")
    print(f"   新品池: {new_pool_path} ({len(kept_new)} 条)")
    print(f"   爆品池: {hot_pool_path} ({len(kept_hot)} 条)")

    return str(new_pool_path), str(hot_pool_path)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DuraTech 周度对比去重")
    parser.add_argument("--new", help="新品原始数据 JSON 路径 (可选，自动查找)")
    parser.add_argument("--hot", help="爆品原始数据 JSON 路径 (可选，自动查找)")
    args = parser.parse_args()
    run_diff(args.new, args.hot)
