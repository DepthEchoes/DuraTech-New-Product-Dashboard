"""
DURATECH 产品追踪可视化看板生成器 v2
- 汇总所有已筛选产品（去重）
- 当前进度列（待调研→调研中→已联系→已送样→已合作→放弃）
- 可视化统计图表
- 进度数据持久化（localStorage）
- 拖拽排序 + 上下移动按钮
- 放弃产品池（"放弃"产品自动移入独立区域）
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import Counter
from html import escape as _html_escape

sys.path.insert(0, str(Path(__file__).parent))
from config import CATEGORIES, CATEGORY_SHORT_NAMES, WORKSPACE_OUTPUT, OUTPUT_DIR


def esc(s):
    """HTML 转义（模板内联 JS 使用）"""
    return _html_escape(s if s is not None else '', quote=True)


PROGRESS_STAGES = ["待调研", "调研中", "已联系", "已送样", "已合作", "放弃"]

STAGE_COLORS = {
    "待调研": "#6c757d",
    "调研中": "#0d6efd",
    "已联系": "#fd7e14",
    "已送样": "#6f42c1",
    "已合作": "#198754",
    "放弃": "#dc3545",
}

LABEL_COLORS = {
    '潜力新品': '#E2EFDA',
    '标准爆品': '#FCE4D6',
    '头部爆品': '#F4B4B4',
}


def _merge_progress_from_db(products):
    """从 board.db 的 progress 表合并 _tracker/_subcategory/_order/_progress 到 products。
    与 web/db.py 的 get_board() 行为一致，确保构建的 board.html 含追踪人数据。"""
    import sqlite3
    db_candidates = [
        Path("/workspace/sellersprite-automation/web/board.db"),
        Path(__file__).parent.parent / "web" / "board.db",
    ]
    db_path = next((p for p in db_candidates if p.exists()), None)
    if not db_path:
        return products
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        prog_rows = {r["asin"]: dict(r) for r in conn.execute(
            "SELECT asin, stage, note, tracker, order_index FROM progress").fetchall()}
        conn.close()
        merged = 0
        for p in products:
            prog = prog_rows.get(p.get("asin", ""))
            if prog:
                p["_progress"] = prog.get("stage") or "待调研"
                p["_subcategory"] = prog.get("note") or ""
                p["_tracker"] = prog.get("tracker") or ""
                p["_order"] = prog.get("order_index") or 0
                merged += 1
        if merged:
            print(f"  [OK] 从 board.db 合并 progress: {merged} 条")
        return products
    except Exception as e:
        print(f"  [WARN] 合并 progress 失败: {e}")
        return products


def collect_all_products():
    """收集所有 uploads 目录下的筛选 JSON，合并去重。
    返回 (products, duplicates)，duplicates 为被去重的 ASIN 明细列表。
    """
    uploads_dir = Path("/root/uploads")
    all_products = {}
    first_seen = {}        # asin -> 首次出现文件名
    duplicates = []        # [{asin, first_file, dup_file, source}, ...]

    # 1) 优先读取已整合的 canonical 商品库（追踪看板唯一数据源）
    canonical = Path(OUTPUT_DIR) / "transferred_products.json"
    if canonical.exists():
        try:
            data = json.loads(canonical.read_text())
            for p in data.get("products", []):
                asin = p.get("asin", "")
                if not asin:
                    continue
                if asin not in all_products:
                    all_products[asin] = p
                    first_seen[asin] = canonical.name
        except Exception as e:
            print(f"  [WARN] 读取 canonical 商品库失败: {e}")

    # 2) 读取 uploads 新转入文件（跳过 consumed 归档目录与进度备份）
    if uploads_dir.exists():
        for f in sorted(uploads_dir.glob("*.json")):
            if "consumed" in str(f):
                continue
            if f.name.startswith("progress_backup"):
                continue
            try:
                data = json.loads(f.read_text())
                products = data.get("products", [])
                if not products:
                    continue
                # 兼容 type 和 pool 两种字段
                source = data.get("type") or data.get("pool") or "unknown"
                for p in products:
                    asin = p.get("asin", "")
                    if not asin:
                        continue
                    if asin not in all_products:
                        p["_progress"] = "待调研"
                        p["_source"] = source
                        all_products[asin] = p
                        first_seen[asin] = f.name
                    else:
                        existing = all_products[asin]
                        # 重复时：用新文件字段补充，但 _source 保留首次来源
                        existing.update(p)
                        existing["_progress"] = existing.get("_progress", "待调研")
                        if existing.get("_source") == "unknown":
                            existing["_source"] = source
                        # 记录重复
                        duplicates.append({
                            "asin": asin,
                            "first_file": first_seen.get(asin, "?"),
                            "dup_file": f.name,
                            "source": source,
                        })
            except Exception as e:
                print(f"  [WARN] 跳过 {f.name}: {e}")

    return list(all_products.values()), duplicates


def load_progress_backup(products):
    """从进度备份文件恢复 _progress。
    查找顺序：/workspace/progress_backup.json → /root/uploads/ 下所有 progress_backup*.json
    优先级：uploads 下的文件覆盖 /workspace 的（越新的越优先）。
    """
    backup_map = {}
    candidates = []
    
    ws_backup = Path("/workspace/progress_backup.json")
    if ws_backup.exists():
        candidates.append(ws_backup)
    
    uploads_dir = Path("/root/uploads")
    if uploads_dir.exists():
        candidates.extend(sorted(uploads_dir.glob("progress_backup*.json")))
    
    for f in candidates:
        try:
            data = json.loads(f.read_text())
            # 兼容两种格式：{asin: progress} 或 {"products":[{asin, _progress}]}
            if isinstance(data, dict):
                if "products" in data:
                    for p in data["products"]:
                        if p.get("asin"):
                            backup_map[p["asin"]] = p.get("_progress", "待调研")
                else:
                    for asin, prog in data.items():
                        backup_map[asin] = prog
            print(f"  [OK] 读取进度备份: {f.name} ({len(backup_map)} 条)")
        except Exception as e:
            print(f"  [WARN] 跳过进度备份 {f.name}: {e}")
    
    if not backup_map:
        return 0
    
    applied = 0
    for p in products:
        if p.get("asin") in backup_map:
            p["_progress"] = backup_map[p["asin"]]
            applied += 1
    return applied


def build_dashboard(output_path=None, **kwargs):
    """生成可视化看板 HTML v2（本地版：数据内嵌，进度存 localStorage）
    支持从 output/pending_transfer.json 读取需求池转入的产品。
    kwargs 用于兼容旧调用（如 web_mode=True），实际不影响本函数行为。
    """
    products, upload_duplicates = collect_all_products()
    _merge_progress_from_db(products)
    load_progress_backup(products)

    # ---- 读取需求池待转入产品 ----
    pending_file = Path(OUTPUT_DIR) / "pending_transfer.json"
    transferred = 0
    pending_duplicates = []   # 已在看板中、被跳过的 ASIN
    if pending_file.exists():
        try:
            pending = json.loads(pending_file.read_text())
            pending_products = pending.get("products", [])
            pool = pending.get("pool", "unknown")
            for pp in pending_products:
                asin = pp.get("asin", "")
                if not asin:
                    continue
                if asin in [p.get("asin") for p in products]:
                    pending_duplicates.append({"asin": asin, "source": pool})
                    continue  # 已有产品不覆盖
                pp["_progress"] = "待调研"
                pp["_source"] = pp.get("_source", pool)
                pp["__label__"] = pp.get("__label__", "潜力新品" if pp.get("_source") == "new" else "标准爆品")
                products.append(pp)
                transferred += 1
            # 转入后删除文件（避免重复导入）
            pending_file.unlink()
            print(f"  [OK] 已从需求池转入 {transferred} 个新产品")
        except Exception as e:
            print(f"  [WARN] 读取待转入产品失败: {e}")

    # ---- 重复去重提示 ----
    all_dupes = upload_duplicates + pending_duplicates
    if all_dupes:
        print(f"\n  [INFO] 检测到 {len(all_dupes)} 个重复 ASIN（已自动去重，保留首次数据）:")
        for d in all_dupes[:30]:
            if "first_file" in d:
                print(f"    - {d['asin']} | 来源: {d['source']} | 首次出现: {d['first_file']} | 重复于: {d['dup_file']}")
            else:
                print(f"    - {d['asin']} | 来源: {d['source']} | 已在追踪看板中存在（pending_transfer 跳过）")
        if len(all_dupes) > 30:
            print(f"    ... 其余 {len(all_dupes) - 30} 个重复略")
    else:
        print(f"  [OK] 无重复 ASIN")

    # ---- 写入 canonical 商品库（唯一数据源）+ 归档已消费的 uploads 文件 ----
    canonical_written = False
    try:
        canonical = Path(OUTPUT_DIR) / "transferred_products.json"
        if not products and canonical.exists():
            # 防数据清空：本次无任何产品时保留现有 canonical，避免空数据覆盖
            print("  [WARN] 本次产品为空，跳过覆盖 canonical（保留现有数据）")
        else:
            canonical.write_text(json.dumps(
                {"products": products, "updated_at": datetime.now().isoformat()},
                ensure_ascii=False), encoding="utf-8")
            print(f"  [OK] 已写入 canonical 商品库: {canonical.name} ({len(products)} 条)")
        canonical_written = True
    except Exception as e:
        print(f"  [WARN] 写入 canonical 商品库失败: {e}")

    # 仅在 canonical 写入成功后才归档，避免数据丢失（移入 consumed/，可还原，不删除）
    if canonical_written:
        try:
            uploads_dir = Path("/root/uploads")
            consumed_dir = uploads_dir / "consumed"
            archived = 0
            if uploads_dir.exists():
                for f in sorted(uploads_dir.glob("*.json")):
                    if "consumed" in str(f):
                        continue
                    if f.name.startswith("progress_backup"):
                        continue
                    try:
                        data = json.loads(f.read_text())
                        if not data.get("products"):
                            continue
                    except Exception:
                        continue
                    consumed_dir.mkdir(exist_ok=True)
                    dest = consumed_dir / f.name
                    if dest.exists():
                        dest = consumed_dir / f"{f.stem}_{datetime.now().strftime('%H%M%S')}{f.suffix}"
                    f.rename(dest)
                    archived += 1
            if archived:
                print(f"  [OK] 已归档 {archived} 个已消费 uploads 文件 → uploads/consumed/")
        except Exception as e:
            print(f"  [WARN] 归档 uploads 文件失败: {e}")

    if not products:
        print("[WARN] 没有找到产品数据")
        return None

    total = len(products)
    by_progress = Counter(p.get("_progress", "待调研") for p in products)
    by_label = Counter(p.get("__label__", "") for p in products)
    by_category = Counter(p.get("category", "") for p in products)

    # 追踪人列表（去重，用于筛选下拉）
    trackers = sorted({(p.get("_tracker") or "").strip() for p in products if (p.get("_tracker") or "").strip()})
    tracker_options = "".join(
        f'<option value="{esc(t)}">{esc(t)}</option>' for t in trackers)
    
    new_count = sum(1 for p in products if p.get("_source") == "new")
    hot_count = sum(1 for p in products if p.get("_source") == "hot")
    abandoned_count = by_progress.get("放弃", 0)
    cooperated_count = by_progress.get("已合作", 0)
    active_count = total - abandoned_count - cooperated_count
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    if output_path is None:
        output_path = Path(WORKSPACE_OUTPUT) / "DuraTech_产品追踪看板.html"

    products_json = json.dumps(products, ensure_ascii=False)
    stage_colors_json = json.dumps(STAGE_COLORS, ensure_ascii=False)
    label_colors_json = json.dumps(LABEL_COLORS, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DuraTech 产品追踪看板 {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<script>Chart.register(ChartDataLabels);</script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "Microsoft YaHei", "微软雅黑", Arial, sans-serif; font-size: 13px; background: #f0f2f5; }}
.header {{ background: linear-gradient(135deg, #1a3a5c, #2F5496); color: #fff; padding: 16px 24px; display: flex; align-items: flex-start; justify-content: space-between; }}
.header .header-left {{ flex: 1; min-width: 0; }}
.header h1 {{ font-size: 20px; margin-bottom: 4px; }}
.header .sub {{ font-size: 12px; opacity: 0.8; }}
.header .nav-link {{ color: rgba(255,255,255,.8); text-decoration: none; font-size: 13px; margin-left: 16px; transition: color .15s; white-space: nowrap; }}
.header .nav-link:hover {{ color: #fff; }}
/* 顶栏右侧缩放控件（自适应分辨率 / 缩放大小） */
.header-right {{ display: flex; align-items: center; }}
.zoom-ctrl {{ display: flex; align-items: center; gap: 4px; background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.3); border-radius: 20px; padding: 4px 8px; }}
.zoom-label {{ font-size: 11px; color: rgba(255,255,255,0.85); margin-right: 2px; }}
.zoom-val {{ font-size: 12px; color: #fff; min-width: 40px; text-align: center; font-weight: 600; }}
.zb {{ width: 22px; height: 22px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.4); background: rgba(255,255,255,0.12); color: #fff; cursor: pointer; font-size: 14px; line-height: 1; display: flex; align-items: center; justify-content: center; font-family: inherit; }}
.zb:hover {{ background: rgba(255,255,255,0.28); }}
/* 看板切换导航（需求池 / 产品追踪） */
.topnav {{ display: flex; gap: 10px; padding: 0 24px; background: linear-gradient(135deg, #16314f, #24447e); }}
.nav-tab {{ display: inline-flex; align-items: center; gap: 6px; padding: 11px 22px; color: rgba(255,255,255,.7); text-decoration: none; font-size: 14px; font-weight: 600; border-bottom: 3px solid transparent; transition: all .15s; white-space: nowrap; }}
.nav-tab:hover {{ color: #fff; text-decoration: none; }}
.nav-tab.active {{ color: #fff; background: rgba(255,255,255,.10); border-bottom-color: #4da3ff; }}
.header h1 {{ font-size: 20px; margin-bottom: 4px; }}
.header .sub {{ font-size: 12px; opacity: 0.8; }}
.stats-row {{ display: grid; grid-template-columns: repeat(8, 1fr); gap: 12px; padding: 16px 24px; }}
.stat-card {{ background: #fff; border-radius: 8px; padding: 14px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); cursor: pointer; transition: transform 0.15s; }}
.stat-card:hover {{ transform: translateY(-2px); }}
.stat-card .num {{ font-size: 28px; font-weight: bold; color: #2F5496; }}
.stat-card .label {{ font-size: 11px; color: #888; margin-top: 4px; }}
.charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 0 24px 16px; }}
.chart-box {{ background: #fff; border-radius: 8px; padding: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.chart-box h3 {{ font-size: 14px; margin-bottom: 10px; color: #333; text-align: center; }}
.chart-box canvas {{ max-height: 250px; }}
.toolbar {{ background: #fff; margin: 0 24px 16px; border-radius: 8px; padding: 10px 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.toolbar select, .toolbar input {{ padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; font-family: inherit; }}
.toolbar button {{ padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-family: inherit; }}
.btn-export {{ background: #2F5496; color: #fff; }}
.btn-export:hover {{ background: #1e3a6e; }}
.btn-import {{ background: #28a745; color: #fff; }}
.btn-import:hover {{ background: #1e7e34; }}
.btn-market {{ background: #f8f9fa; color: #2F5496; border: 1px solid #d6dbe0; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 11px; white-space: nowrap; }}
.btn-market:hover {{ background: #e8f0fe; border-color: #2F5496; }}
.market-cell {{ min-width: 60px; }}
.btn-reset {{ background: #6c757d; color: #fff; }}
.toolbar .count {{ margin-left: auto; font-weight: bold; color: #2F5496; }}
/* 放弃产品池 */
.abandoned-section {{ margin: 0 24px 16px; }}
.abandoned-header {{ background: #fff; border-radius: 8px; padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid #dc3545; }}
.abandoned-header:hover {{ background: #fff5f5; }}
.abandoned-header h3 {{ font-size: 14px; color: #dc3545; }}
.abandoned-header .badge {{ background: #dc3545; color: #fff; border-radius: 10px; padding: 2px 10px; font-size: 12px; margin-left: 8px; }}
.abandoned-header .arrow {{ transition: transform 0.3s; font-size: 18px; }}
.abandoned-header .arrow.open {{ transform: rotate(180deg); }}
.abandoned-body {{ display: none; background: #fff; border-radius: 0 0 8px 8px; overflow: visible; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.abandoned-body.open {{ display: block; }}
/* 表格 */
.table-wrap {{ margin: 0 24px 24px; background: #fff; border-radius: 8px; overflow: visible; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0; }}
th {{ background: #2F5496; color: #fff; padding: 8px 6px; font-size: 11px; text-align: center; white-space: nowrap; position: sticky; top: 0; z-index: 5; }}
td {{ padding: 6px; border-bottom: 1px solid #eee; font-size: 11px; text-align: center; vertical-align: middle; }}
tr:hover {{ background: #f8f9ff; }}
tr.dragging {{ opacity: 0.5; background: #e3f2fd !important; }}
tr.drag-over {{ border-top: 3px solid #2F5496 !important; }}
tr.drag-over td {{ background: #e8f0fe !important; }}
img.product-img {{ width: 120px; height: 120px; object-fit: contain; border: 1px solid #eee; border-radius: 4px; background: #fafafa; }}
.progress-select {{ padding: 3px 6px; border-radius: 4px; font-size: 11px; font-family: inherit; cursor: pointer; border: 2px solid; font-weight: bold; }}
.stage-待调研 {{ background: #e9ecef; border-color: #6c757d; color: #495057; }}
.stage-调研中 {{ background: #cfe2ff; border-color: #0d6efd; color: #084298; }}
.stage-已联系 {{ background: #ffe5d0; border-color: #fd7e14; color: #8a4500; }}
.stage-已送样 {{ background: #e2d9f3; border-color: #6f42c1; color: #432874; }}
.stage-已合作 {{ background: #d1e7dd; border-color: #198754; color: #0a3622; }}
.stage-放弃 {{ background: #f8d7da; border-color: #dc3545; color: #6b111a; }}
/* 追踪人输入框（适配约三个汉字宽度，hover/focus 展开方便输入） */
.tracker-input {{
  width: 36px;
  min-width: 36px;
  max-width: 36px;
  height: 24px;
  padding: 2px 4px;
  border: 1px solid #ddd;
  border-radius: 3px;
  font-size: 11px;
  font-family: inherit;
  background: #fafafa;
  text-align: center;
  box-sizing: border-box;
  transition: all 0.2s ease;
}}
.tracker-input:hover,
.tracker-input:focus {{
  border-color: #2F5496;
  outline: none;
  background: #fff;
  max-width: none;
  width: 90px;
}}
/* 进度输入框所在单元格：提供定位上下文，让 hover 浮层正确展开 */
td:has(> .subcategory-input) {{ position: relative; }}

/* 进度输入框所在单元格：提供定位上下文，让 hover 浮层正确展开 */
td:has(> .subcategory-input) {{ position: relative; }}

/* 进度输入框（原品类列，手动输入备注 / textarea，多行可滚动） */
.subcategory-input {{
  width: 210px;
  height: 120px;
  padding: 4px 6px;
  border: 1px solid #ddd;
  border-radius: 3px;
  font-size: 12px;
  font-family: inherit;
  background: #fafafa;
  white-space: pre-wrap;
  overflow: auto;
  transition: all 0.2s ease;
  cursor: text;
  line-height: 1.4;
  resize: none;
  box-sizing: border-box;
}}
/* hover / focus 时：仅边框高亮提示 */
.subcategory-input:hover,
.subcategory-input:focus {{
  border-color: #2F5496;
  outline: none;
  background: #fff;
}}
.title-cell {{ max-width: 180px; word-wrap: break-word; text-align: left; }}
.num-cell {{ text-align: center; white-space: nowrap; }}
.price-cell {{ color: #c00; font-weight: bold; }}
.rating {{ color: #f0ad4e; font-weight: bold; }}
/* 查竞品刷新后的变化标注（销量/月销额/售价下方小字） */
.cell-delta {{ font-size: 10px; font-weight: bold; margin-top: 2px; white-space: nowrap; line-height: 1.2; }}
.cell-delta .delta-up {{ color: #16a34a; }}
.cell-delta .delta-down {{ color: #dc3545; }}
.cell-delta .delta-flat {{ color: #999; font-weight: normal; }}
.cell-delta .delta-bsr {{ color: #2F5496; font-weight: normal; }}
a {{ color: #2F5496; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
/* 移动按钮 */
.move-btns {{ display: flex; flex-direction: column; gap: 2px; }}
.move-btn {{ width: 22px; height: 18px; border: 1px solid #ccc; background: #f8f9fa; cursor: pointer; font-size: 10px; line-height: 1; color: #666; border-radius: 2px; display: flex; align-items: center; justify-content: center; }}
.move-btn:hover {{ background: #2F5496; color: #fff; border-color: #2F5496; }}
.move-btn:disabled {{ opacity: 0.3; cursor: not-allowed; }}
.move-btn:disabled:hover {{ background: #f8f9fa; color: #666; border-color: #ccc; }}
/* 拖拽手柄 */
.drag-handle {{ cursor: grab; color: #ccc; font-size: 16px; user-select: none; padding: 0 4px; }}
.drag-handle:hover {{ color: #2F5496; }}
.drag-handle:active {{ cursor: grabbing; }}
/* Toast */
.toast {{ position: fixed; top: 20px; right: 20px; background: #28a745; color: #fff; padding: 10px 20px; border-radius: 4px; z-index: 9999; display: none; font-size: 13px; }}
/* 恢复按钮 */
.btn-restore {{ background: none; border: 1px solid #198754; color: #198754; cursor: pointer; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-family: inherit; }}
.btn-restore:hover {{ background: #198754; color: #fff; }}
@media (max-width: 1200px) {{ .charts-row {{ grid-template-columns: 1fr 1fr; }} .stats-row {{ grid-template-columns: repeat(4, 1fr); }} }}
@media (max-width: 768px) {{ .stats-row {{ grid-template-columns: repeat(2, 1fr); }} .charts-row {{ grid-template-columns: 1fr; }} }}
@media (max-width: 560px) {{ .stats-row {{ grid-template-columns: repeat(2, 1fr); }} .table-wrap table {{ min-width: 1400px; }} .toolbar {{ gap: 6px; }} }}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>📊 DuraTech 产品追踪看板</h1>
    <div class="sub">更新于 {date_str} · 新品 {new_count} 个 · 爆品 {hot_count} 个 · 进行中 {active_count} 个 · 已合作 {cooperated_count} 个 · 放弃 {abandoned_count} 个</div>
  </div>
  <div class="header-right">
    <div class="zoom-ctrl">
      <span class="zoom-label">缩放</span>
      <button class="zb" onclick="zoomOut()" title="缩小">−</button>
      <span id="zoomVal" class="zoom-val">100%</span>
      <button class="zb" onclick="zoomIn()" title="放大">+</button>
      <button class="zb" onclick="zoomReset()" title="重置">⟳</button>
    </div>
  </div>
</div>

<div class="topnav">
  <a href="/" class="nav-tab">📋 需求池看板 →</a>
  <a href="/tracking" class="nav-tab active">📊 产品追踪看板</a>
</div>

<div class="stats-row" id="statsRow">
  <div class="stat-card" onclick="quickFilter('all')"><div class="num" id="statTotal">{total}</div><div class="label">产品总数</div></div>
  <div class="stat-card" onclick="quickFilter('待调研')"><div class="num" id="statPending">{by_progress.get("待调研", 0)}</div><div class="label">待调研</div></div>
  <div class="stat-card" onclick="quickFilter('调研中')"><div class="num" id="statResearching" style="color:#0d6efd">{by_progress.get("调研中", 0)}</div><div class="label">调研中</div></div>
  <div class="stat-card" onclick="quickFilter('已联系')"><div class="num" id="statContacted" style="color:#fd7e14">{by_progress.get("已联系", 0)}</div><div class="label">已联系</div></div>
  <div class="stat-card" onclick="quickFilter('已送样')"><div class="num" id="statSample">{by_progress.get("已送样", 0)}</div><div class="label">已送样</div></div>
  <div class="stat-card" onclick="quickFilter('已合作')"><div class="num" style="color:#198754" id="statDone">{by_progress.get("已合作", 0)}</div><div class="label">已合作</div></div>
  <div class="stat-card" onclick="document.getElementById('abandonedSection').scrollIntoView({{behavior:'smooth'}});toggleAbandoned(true)"><div class="num" style="color:#dc3545" id="statAbandoned">{abandoned_count}</div><div class="label">已放弃</div></div>
  <div class="stat-card"><div class="num" style="color:#0d6efd">{active_count}</div><div class="label">进行中</div></div>
</div>

<div class="charts-row">
  <div class="chart-box"><h3>📈 进度分布</h3><canvas id="chartProgress"></canvas></div>
  <div class="chart-box"><h3>📂 类目分布</h3><canvas id="chartCategory"></canvas></div>
</div>

<div class="toolbar">
  <label>进度筛选:</label>
  <select id="filterProgress" onchange="applyFilters()">
    <option value="all">全部进行中</option>
    {''.join(f'<option value="{s}">{s}</option>' for s in PROGRESS_STAGES)}
  </select>
  <label>类目:</label>
  <select id="filterCategory" onchange="applyFilters()">
    <option value="all">全部类目</option>
  </select>
  <label>追踪人:</label>
  <select id="filterTracker" onchange="applyFilters()">
    <option value="all">全部追踪人</option>
  </select>
  <label>搜索:</label>
  <input type="text" id="filterSearch" placeholder="ASIN/标题..." oninput="applyFilters()">
  <span style="margin-left:8px;color:#888">|</span>
  <label>📋 批量更改进度:</label>
  <select id="batchProgress" onchange="batchUpdateProgress(this.value);this.value=''" style="min-width:110px">
    <option value="">-- 选择进度 --</option>
    {''.join(f'<option value="{s}">{s}</option>' for s in PROGRESS_STAGES)}
  </select>
  <span style="color:#888;font-size:11px">已选 <b id="selectedCount">0</b> 个</span>
  <button class="btn-export" onclick="exportCSV()">📥 导出 CSV</button>
  <button class="btn-import" onclick="startUpdateOrUpload()" style="background:#0d6efd" title="自动检测Cookie：有效直接开始更新，过期提示上传">🔍 产品信息更新</button>
  <button class="btn-import" onclick="openAddAsinModal()" style="background:#6f42c1">➕ 添加 ASIN</button>
  <button class="btn-reset" onclick="resetAll()">🔄 重置排序</button>
  <span class="count">显示: <span id="visibleCount">{active_count}</span>/{active_count} 进行中</span>
</div>

<!-- 活跃产品表格 -->
<div class="table-wrap" id="activeTableWrap">
<table id="productTable">
<thead>
<tr>
  <th style="width:28px"><input type="checkbox" id="checkAllActive" onchange="toggleAll(this, 'active')" title="全选"></th>
  <th style="width:50px">排序</th>
  <th style="width:52px">追踪人</th>
  <th>主图</th>
  <th style="cursor:pointer" onclick="sortByCategory()" title="点击按四大类顺序升/降序排序">类目 ⇅</th>
  <th style="width:220px">进度</th>
  <th>ASIN</th>
  <th style="width:180px">标题</th>
  <th>来源</th>
  <th>近30天销量</th>
  <th>售价</th>
  <th>上架时间</th>
  <th>评分</th>
  <th>📎 市场分析</th>
  <th style="min-width:100px">📌 当前进度</th>
</tr>
</thead>
<tbody id="tableBody"></tbody>
</table>
</div>

<!-- 已合作产品池 -->
<div class="abandoned-section" id="cooperatedSection">
  <div class="abandoned-header" onclick="toggleCooperated()" style="border-left-color:#198754">
    <div>
      <h3 style="color:#198754">✅ 已合作产品池 <span class="badge" id="cooperatedBadge" style="background:#198754">{cooperated_count}</span></h3>
    </div>
    <span class="arrow" id="cooperatedArrow">▼</span>
  </div>
  <div class="abandoned-body" id="cooperatedBody">
    <div class="table-wrap" style="margin:0;box-shadow:none;border-radius:0">
    <table>
    <thead>
    <tr>
      <th style="width:50px">排序</th>
      <th style="width:52px">追踪人</th>
      <th>主图</th>
      <th style="cursor:pointer" onclick="sortByCategory()" title="点击按四大类顺序升/降序排序">类目 ⇅</th>
      <th style="width:220px">进度</th>
      <th>ASIN</th>
      <th style="width:180px">标题</th>
      <th>来源</th>
      <th>近30天销量</th>
      <th>售价</th>
      <th>上架时间</th>
      <th>评分</th>
  <th>📎 市场分析</th>
  <th style="min-width:140px">📌 状态</th>
    </tr>
    </thead>
    <tbody id="cooperatedBodyTable"></tbody>
    </table>
    </div>
  </div>
</div>

<!-- 放弃产品池 -->
<div class="abandoned-section" id="abandonedSection">
  <div class="abandoned-header" onclick="toggleAbandoned()">
    <div>
      <h3>🗑️ 放弃产品池 <span class="badge" id="abandonedBadge">{abandoned_count}</span></h3>
    </div>
    <span class="arrow" id="abandonedArrow">▼</span>
  </div>
  <div class="abandoned-body" id="abandonedBody">
    <div class="table-wrap" style="margin:0;box-shadow:none;border-radius:0">
    <table>
    <thead>
    <tr>
      <th style="width:50px">排序</th>
      <th style="width:52px">追踪人</th>
      <th>主图</th>
      <th style="cursor:pointer" onclick="sortByCategory()" title="点击按四大类顺序升/降序排序">类目 ⇅</th>
      <th style="width:220px">进度</th>
      <th>ASIN</th>
      <th style="width:180px">标题</th>
      <th>来源</th>
      <th>近30天销量</th>
      <th>售价</th>
      <th>上架时间</th>
      <th>评分</th>
  <th>📎 市场分析</th>
  <th style="min-width:140px">📌 状态</th>
    </tr>
    </thead>
    <tbody id="abandonedBodyTable"></tbody>
    </table>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<!-- 手动添加 ASIN 弹窗 -->
<div id="addAsinModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:3000;align-items:center;justify-content:center" onclick="if(event.target===this)closeAddAsinModal()">
  <div style="background:#fff;border-radius:10px;width:440px;max-width:94vw;padding:20px 24px;box-shadow:0 12px 48px rgba(0,0,0,.2)">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      <b style="font-size:15px;color:#2F5496">➕ 手动添加产品</b>
      <span onclick="closeAddAsinModal()" style="cursor:pointer;font-size:22px;color:#999;line-height:1">&times;</span>
    </div>
    <div style="font-size:12px;color:#666;margin-bottom:8px">输入父(子)体 ASIN 或产品链接，将自动从卖家精灵获取产品信息并加入追踪看板</div>
    <input type="text" id="addAsinInput" placeholder="如 B00FLYWNYQ" style="width:100%;padding:9px 12px;border:1px solid #ccc;border-radius:6px;font-size:13px;box-sizing:border-box" onkeydown="if(event.key==='Enter')doAddAsin()">
    <div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end">
      <button onclick="closeAddAsinModal()" style="background:#6c757d;color:#fff;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:13px">取消</button>
      <button onclick="doAddAsin()" style="background:#2F5496;color:#fff;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:13px">添加</button>
    </div>
    <div id="addAsinMsg" style="margin-top:10px;font-size:12px;color:#198754"></div>
  </div>
</div>

<!-- 卖家精灵 Cookie 上传浮层（产品信息更新 / 手动添加 ASIN 共用，样式对齐需求池看板） -->
<div id="lookupCard" style="position:fixed;top:80px;right:24px;width:430px;max-width:calc(100vw - 48px);background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.18);padding:16px;z-index:2600;display:none">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
    <b id="lookupCardTitle" style="font-size:14px">🍪 卖家精灵 Cookie</b>
    <span onclick="closeLookupCard()" style="cursor:pointer;font-size:20px;line-height:1;color:#999;padding:2px 6px;border-radius:4px" title="关闭">&times;</span>
  </div>
  <div id="lookupHint" style="font-size:11px;color:#666;margin-bottom:8px"></div>
  <div id="lookupUploadArea">
    <input type="file" id="lookupCookieFile" accept=".json,.txt" style="border:none;font-size:12px;width:100%">
    <div style="margin-top:8px">
      <button style="background:#28a745;color:#fff;font-weight:bold;padding:7px 16px;border:none;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit" onclick="uploadLookupCookie()">📤 确认上传</button>
    </div>
    <textarea id="lookupCookieText" rows="2" placeholder="或直接粘贴 EditThisCookie 导出的 JSON 文本..." style="width:100%;margin-top:8px;font-size:11px;box-sizing:border-box;padding:6px"></textarea>
  </div>
  <div id="lookupPanel" style="display:none;margin-top:12px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <span id="luStep" style="font-size:12px;font-weight:bold;color:#2F5496">准备中…</span>
      <span id="luPct" style="font-size:14px;font-weight:bold;color:#2F5496">0%</span>
    </div>
    <div style="background:#e9ecef;border-radius:8px;height:22px;overflow:hidden;position:relative">
      <div id="luBar" style="width:0%;height:100%;background:linear-gradient(90deg,#2F5496,#28a745);transition:width .5s;border-radius:8px"></div>
    </div>
    <div id="luLabel" style="font-size:11px;color:#666;margin-top:6px"></div>
    <pre id="luLog" style="background:#1a1a2e;color:#7ee787;font-size:10px;border-radius:4px;padding:8px;max-height:150px;overflow:auto;white-space:pre-wrap;margin:6px 0 0"></pre>
  </div>
</div>

<!-- 市场分析附件弹窗 -->
<div id="marketModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:3100;align-items:center;justify-content:center" onclick="if(event.target===this)closeMarketModal()">
  <div style="background:#fff;border-radius:10px;width:520px;max-width:94vw;max-height:80vh;display:flex;flex-direction:column;padding:20px 24px;box-shadow:0 12px 48px rgba(0,0,0,.2)">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      <b style="font-size:15px;color:#2F5496">📎 市场分析 · <span id="marketAsin" style="font-weight:normal;color:#666"></span></b>
      <span onclick="closeMarketModal()" style="cursor:pointer;font-size:22px;color:#999;line-height:1">&times;</span>
    </div>
    <div style="font-size:12px;color:#666;margin-bottom:8px">支持 HTML / Excel，可上传多个附件；点击附件名在新标签页打开预览</div>
    <div id="marketList" style="flex:1;overflow:auto;min-height:120px;border:1px solid #eee;border-radius:6px;padding:8px;font-size:12px;color:#888">加载中…</div>
    <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
      <input type="file" id="marketFileInput" multiple accept=".html,.htm,.xlsx,.xls" style="flex:1;font-size:12px">
      <button onclick="uploadMarketFile()" style="background:#2F5496;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;white-space:nowrap">上传附件</button>
    </div>
    <div id="marketMsg" style="margin-top:8px;font-size:12px;color:#198754"></div>
  </div>
</div>

<script>
// ===== 数据 =====
const PRODUCTS = {products_json};
const STAGE_COLORS = {stage_colors_json};
const LABEL_COLORS = {label_colors_json};
const PROGRESS_STAGES = {json.dumps(PROGRESS_STAGES, ensure_ascii=False)};
const CATEGORY_SHORT = {json.dumps({k: CATEGORY_SHORT_NAMES.get(k, k) for k in by_category.keys()}, ensure_ascii=False)};

// ===== localStorage keys =====
const STORAGE_PROGRESS = 'duratech_product_progress';
const STORAGE_ORDER = 'duratech_product_order';
const STORAGE_SUBCATEGORY = 'duratech_product_subcategory';

// ===== 服务端自动保存（编辑后回写数据库，跨设备/浏览器持久化）=====
const TOKEN_KEY = 'duratech_pool_token';
function getTok() {{ return localStorage.getItem(TOKEN_KEY) || ''; }}
let _autosaveReady = false;
let _autosaveTimer = null;
function autosave() {{
  if (!_autosaveReady) return;
  if (_autosaveTimer) clearTimeout(_autosaveTimer);
  _autosaveTimer = setTimeout(doAutosave, 800);
}}
function doAutosave() {{
  const edits = {{}};
  PRODUCTS.forEach(function(p, i) {{
    edits[p.asin] = {{ progress: p._progress, subcategory: p._subcategory || '', tracker: p._tracker || '', order: i }};
  }});
  const t = getTok();
  fetch('/api/tracking/edits', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + t }},
    body: JSON.stringify({{ edits: edits }})
  }}).catch(function() {{}});
}}
async function loadServerEdits() {{
  try {{
    const t = getTok();
    const r = await fetch('/api/tracking/edits', {{ headers: {{ 'Authorization': 'Bearer ' + t }} }});
    if (!r.ok) return;
    const d = await r.json();
    const edits = (d && d.edits) || {{}};
    PRODUCTS.sort(function(a, b) {{
      const oa = edits[a.asin] ? (edits[a.asin].order || 0) : 99999;
      const ob = edits[b.asin] ? (edits[b.asin].order || 0) : 99999;
      if (oa !== ob) return oa - ob;
      return (a.asin || '').localeCompare(b.asin || '');
    }});
    PRODUCTS.forEach(function(p) {{
      const e = edits[p.asin];
      if (e) {{
        if (e.progress) p._progress = e.progress;
        if (e.subcategory !== undefined) p._subcategory = e.subcategory;
        if (e.tracker !== undefined) p._tracker = e.tracker;
      }}
    }});
  }} catch (e) {{}}
}}

// ===== 排序持久化 =====
function loadOrder() {{
  try {{
    const saved = JSON.parse(localStorage.getItem(STORAGE_ORDER) || '[]');
    if (saved.length > 0) {{
      const orderMap = {{}};
      saved.forEach((asin, i) => {{ orderMap[asin] = i; }});
      PRODUCTS.sort((a, b) => {{
        const ai = orderMap[a.asin] !== undefined ? orderMap[a.asin] : 99999;
        const bi = orderMap[b.asin] !== undefined ? orderMap[b.asin] : 99999;
        return ai - bi;
      }});
    }}
  }} catch(e) {{}}
}}

function saveOrder() {{
  const order = PRODUCTS.map(p => p.asin);
  localStorage.setItem(STORAGE_ORDER, JSON.stringify(order));
  autosave();
}}

// ===== 进度持久化 =====
function loadProgress() {{
  try {{
    const saved = JSON.parse(localStorage.getItem(STORAGE_PROGRESS) || '{{}}');
    PRODUCTS.forEach(p => {{
      // 以文件内嵌进度（由进度备份经生成器写入）为准，避免浏览器旧 localStorage 覆盖本次更新；
      // 仅当某商品内嵌进度缺失时才回退到本地记录
      if (!p._progress && saved[p.asin]) p._progress = saved[p.asin];
    }});
  }} catch(e) {{}}
}}

function saveProgress() {{
  const data = {{}};
  PRODUCTS.forEach(p => {{ data[p.asin] = p._progress; }});
  localStorage.setItem(STORAGE_PROGRESS, JSON.stringify(data));
  autosave();
}}

// ===== 进度列持久化（手动输入，原品类列） =====
function loadSubcategories() {{
  try {{
    const saved = JSON.parse(localStorage.getItem(STORAGE_SUBCATEGORY) || '{{}}');
    PRODUCTS.forEach(p => {{
      if (saved[p.asin]) p._subcategory = saved[p.asin];
    }});
  }} catch(e) {{}}
}}

function saveSubcategories() {{
  const data = {{}};
  PRODUCTS.forEach(p => {{ if (p._subcategory) data[p.asin] = p._subcategory; }});
  localStorage.setItem(STORAGE_SUBCATEGORY, JSON.stringify(data));
  autosave();
}}

// HTML 转义（用于 textarea 内容 / title 属性）
function escHtml(s) {{
  return (s === null || s === undefined ? '' : String(s))
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\"/g, '&quot;').replace(/'/g, '&#39;');
}}

// 文本框按内容自动撑高（仅手动 Enter 换行，不自动软折行）
function autoGrow(ta) {{
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
}}

function updateSubcategory(asin, value) {{
  const p = PRODUCTS.find(x => x.asin === asin);
  if (p) {{
    p._subcategory = value.replace(/\\s+$/g, '');  // 去尾部空白，保留手动换行
    saveSubcategories();
    // 同步 title，使 hover 浮层展示最新文字
    const el = document.querySelector(`#tableBody tr[data-asin="${{asin}}"] .subcategory-input`);
    if (el) el.title = value.replace(/\\s+$/g, '');
  }}
}}

function updateTracker(asin, value) {{
  const p = PRODUCTS.find(x => x.asin === asin);
  if (p) {{
    p._tracker = value.trim();
    autosave();
  }}
  refreshToolbarFilters();
}}

// ===== 获取活跃/已合作/放弃产品 =====
function getActive() {{ return PRODUCTS.filter(p => p._progress !== '放弃' && p._progress !== '已合作'); }}
function getCooperated() {{ return PRODUCTS.filter(p => p._progress === '已合作'); }}
function getAbandoned() {{ return PRODUCTS.filter(p => p._progress === '放弃'); }}

// ===== 渲染表格 =====
function renderAll() {{
  renderActiveTable();
  renderCooperatedTable();
  renderAbandonedTable();
  updateCooperatedBadge();
  updateAbandonedBadge();
  refreshToolbarFilters();   // 数据变化后同步类目/追踪人下拉（自动抓取所有值）
  scheduleMarketCounts();    // 渲染后刷新各行的市场分析附件数
}}

// 市场分析计数去抖刷新（排序/筛选/任何重渲染后调用，保证计数与实际附件一致）
let _mktCountTimer = null;
function scheduleMarketCounts() {{
  if (_mktCountTimer) clearTimeout(_mktCountTimer);
  _mktCountTimer = setTimeout(loadMarketCounts, 250);
}}

function renderActiveTable(filtered) {{
  const tbody = document.getElementById('tableBody');
  const products = filtered !== undefined ? filtered : getActive();
  tbody.innerHTML = '';
  
  products.forEach((p, idx) => {{
    tbody.appendChild(createRow(p, idx, products.length, 'active'));
  }});
  
  scheduleMarketCounts();   // 筛选（进度/类目/追踪人）后保持市场分析计数正确
  document.getElementById('visibleCount').textContent = products.length;
  document.getElementById('checkAllActive').checked = false;
  updateSelectedCount();
}}

function renderAbandonedTable() {{
  const tbody = document.getElementById('abandonedBodyTable');
  const products = getAbandoned();
  tbody.innerHTML = '';
  
  products.forEach((p, idx) => {{
    tbody.appendChild(createRow(p, idx, products.length, 'abandoned'));
  }});
}}

function renderCooperatedTable() {{
  const tbody = document.getElementById('cooperatedBodyTable');
  const products = getCooperated();
  tbody.innerHTML = '';
  
  products.forEach((p, idx) => {{
    tbody.appendChild(createRow(p, idx, products.length, 'cooperated'));
  }});
}}

function createRow(p, idx, total, mode) {{
  const tr = document.createElement('tr');
  tr.dataset.asin = p.asin;
  tr.dataset.category = p.category || '';
  tr.dataset.progress = p._progress;
  tr.dataset.label = p.__label__ || '';
  tr.draggable = true;
  
  const catShort = p.category || '其他';
  const subCategory = p._subcategory || '';
  const sourceLabel = p._source === 'new' ? '🆕新品' : (p._source === 'hot' ? '🔥爆品' : (p._source === 'manual' ? '🔍手动' : p._source));
  const img = p.image ? `<img class="product-img" src="${{p.image}}" loading="lazy" onerror="this.style.display='none'">` : '';
  const stageClass = 'stage-' + p._progress;
  
  const moveBtns = `
    <div class="move-btns">
      <button class="move-btn" ${{idx === 0 ? 'disabled' : ''}} onclick="moveRow(event, '${{p.asin}}', -1)" title="上移">▲</button>
      <button class="move-btn" ${{idx === total - 1 ? 'disabled' : ''}} onclick="moveRow(event, '${{p.asin}}', 1)" title="下移">▼</button>
    </div>`;
  
  if (mode === 'active') {{
    tr.innerHTML = `
      <td style="text-align:center"><input type="checkbox" class="row-checkbox" data-asin="${{p.asin}}" onchange="updateSelectedCount()"></td>
      <td style="text-align:center">
        <span class="drag-handle" title="拖拽排序">⋮⋮</span>
        ${{moveBtns}}
      </td>
      <td><input class="tracker-input" value="${{escHtml(p._tracker || '')}}" placeholder="填写" onchange="updateTracker('${{p.asin}}', this.value)"></td>
      <td>${{img}}</td>
      <td>${{escHtml(catShort)}}</td>
      <td><textarea class="subcategory-input" rows="1" wrap="off" title="${{escHtml(subCategory)}}" placeholder="输入进度…（Enter 换行）" onchange="updateSubcategory('${{p.asin}}', this.value)">${{escHtml(subCategory)}}</textarea></td>
      <td><a href="https://www.amazon.com/dp/${{p.asin}}" target="_blank">${{p.asin}}</a></td>
      <td class="title-cell" title="${{escHtml(p.title || '')}}">${{escHtml(p.title || '')}}</td>
      <td>${{escHtml(sourceLabel)}}</td>
      <td class="num-cell">${{p.sales || ''}}${{deltaNote(p, 'sales')}}</td>
      <td class="num-cell price-cell">${{p.price || ''}}${{deltaNote(p, 'price')}}</td>
      <td>${{p.available || ''}}</td>
      <td class="num-cell rating">${{p.rating || ''}}</td>
      <td class="market-cell" style="text-align:center">
        <button class="btn-market" onclick="openMarketModal('${{p.asin}}')" title="上传/查看市场分析附件">📎 <span id="mktcnt_${{p.asin}}">0</span></button>
      </td>
      <td>
        <select class="progress-select ${{stageClass}}" onchange="updateProgress('${{p.asin}}', this.value)">
          ${{PROGRESS_STAGES.map(s => `<option value="${{s}}" ${{p._progress === s ? 'selected' : ''}}>${{s}}</option>`).join('')}}
        </select>
      </td>`;
  }} else if (mode === 'cooperated') {{
    // 已合作模式
    tr.innerHTML = `
      <td style="text-align:center">${{moveBtns}}</td>
      <td><input class="tracker-input" value="${{escHtml(p._tracker || '')}}" placeholder="填写" onchange="updateTracker('${{p.asin}}', this.value)"></td>
      <td>${{img}}</td>
      <td>${{escHtml(catShort)}}</td>
      <td><textarea class="subcategory-input" rows="1" wrap="off" title="${{escHtml(subCategory)}}" placeholder="输入进度…（Enter 换行）" onchange="updateSubcategory('${{p.asin}}', this.value)">${{escHtml(subCategory)}}</textarea></td>
      <td><a href="https://www.amazon.com/dp/${{p.asin}}" target="_blank">${{p.asin}}</a></td>
      <td class="title-cell" title="${{escHtml(p.title || '')}}">${{escHtml(p.title || '')}}</td>
      <td>${{escHtml(sourceLabel)}}</td>
      <td class="num-cell">${{p.sales || ''}}${{deltaNote(p, 'sales')}}</td>
      <td class="num-cell price-cell">${{p.price || ''}}${{deltaNote(p, 'price')}}</td>
      <td>${{p.available || ''}}</td>
      <td class="num-cell rating">${{p.rating || ''}}</td>
      <td class="market-cell" style="text-align:center">
        <button class="btn-market" onclick="openMarketModal('${{p.asin}}')" title="上传/查看市场分析附件">📎 <span id="mktcnt_${{p.asin}}">0</span></button>
      </td>
      <td>
        <select class="progress-select ${{stageClass}}" onchange="updateProgress('${{p.asin}}', this.value)">
          ${{PROGRESS_STAGES.map(s => `<option value="${{s}}" ${{p._progress === s ? 'selected' : ''}}>${{s}}</option>`).join('')}}
        </select>
        <button class="btn-restore" onclick="updateProgress('${{p.asin}}', '调研中');return false" title="移回进行中">↩ 移回</button>
      </td>`;
  }} else {{
    // 放弃模式
    tr.innerHTML = `
      <td style="text-align:center">${{moveBtns}}</td>
      <td><input class="tracker-input" value="${{escHtml(p._tracker || '')}}" placeholder="填写" onchange="updateTracker('${{p.asin}}', this.value)"></td>
      <td>${{img}}</td>
      <td>${{escHtml(catShort)}}</td>
      <td><textarea class="subcategory-input" rows="1" wrap="off" title="${{escHtml(subCategory)}}" placeholder="输入进度…（Enter 换行）" onchange="updateSubcategory('${{p.asin}}', this.value)">${{escHtml(subCategory)}}</textarea></td>
      <td><a href="https://www.amazon.com/dp/${{p.asin}}" target="_blank">${{p.asin}}</a></td>
      <td class="title-cell" title="${{escHtml(p.title || '')}}">${{escHtml(p.title || '')}}</td>
      <td>${{escHtml(sourceLabel)}}</td>
      <td class="num-cell">${{p.sales || ''}}${{deltaNote(p, 'sales')}}</td>
      <td class="num-cell price-cell">${{p.price || ''}}${{deltaNote(p, 'price')}}</td>
      <td>${{p.available || ''}}</td>
      <td class="num-cell rating">${{p.rating || ''}}</td>
      <td class="market-cell" style="text-align:center">
        <button class="btn-market" onclick="openMarketModal('${{p.asin}}')" title="上传/查看市场分析附件">📎 <span id="mktcnt_${{p.asin}}">0</span></button>
      </td>
      <td>
        <select class="progress-select ${{stageClass}}" onchange="updateProgress('${{p.asin}}', this.value)">
          ${{PROGRESS_STAGES.map(s => `<option value="${{s}}" ${{p._progress === s ? 'selected' : ''}}>${{s}}</option>`).join('')}}
        </select>
        <button class="btn-restore" onclick="updateProgress('${{p.asin}}', '待调研');return false" title="恢复到待调研">↩ 恢复</button>
      </td>`;
  }}
  
  // 拖拽事件
  tr.addEventListener('dragstart', handleDragStart);
  tr.addEventListener('dragend', handleDragEnd);
  tr.addEventListener('dragover', handleDragOver);
  tr.addEventListener('dragleave', handleDragLeave);
  tr.addEventListener('drop', handleDrop);
  
  return tr;
}}

// ===== 拖拽排序 =====
let dragSrcAsin = null;

function handleDragStart(e) {{
  dragSrcAsin = this.dataset.asin;
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', this.dataset.asin);
}}

function handleDragEnd(e) {{
  this.classList.remove('dragging');
  dragSrcAsin = null;
  document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
}}

function handleDragOver(e) {{
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  if (this.dataset.asin !== dragSrcAsin) {{
    this.classList.add('drag-over');
  }}
}}

function handleDragLeave(e) {{
  this.classList.remove('drag-over');
}}

function handleDrop(e) {{
  e.preventDefault();
  this.classList.remove('drag-over');
  const targetAsin = this.dataset.asin;
  if (dragSrcAsin && dragSrcAsin !== targetAsin) {{
    moveProduct(dragSrcAsin, targetAsin);
  }}
}}

function moveProduct(srcAsin, targetAsin) {{
  const srcIdx = PRODUCTS.findIndex(p => p.asin === srcAsin);
  const targetIdx = PRODUCTS.findIndex(p => p.asin === targetAsin);
  if (srcIdx === -1 || targetIdx === -1) return;
  
  // 移动
  const [moved] = PRODUCTS.splice(srcIdx, 1);
  PRODUCTS.splice(targetIdx, 0, moved);
  
  saveOrder();
  renderAll();
  applyFilters();
}}

// ===== 批量操作 =====
function toggleAll(checkbox, mode) {{
  const checkboxes = document.querySelectorAll('#tableBody .row-checkbox');
  checkboxes.forEach(cb => cb.checked = checkbox.checked);
  updateSelectedCount();
}}

function updateSelectedCount() {{
  const checkboxes = document.querySelectorAll('#tableBody .row-checkbox:checked');
  document.getElementById('selectedCount').textContent = checkboxes.length;
}}

function batchUpdateProgress(newStage) {{
  if (!newStage) return;
  const checkboxes = document.querySelectorAll('#tableBody .row-checkbox:checked');
  if (checkboxes.length === 0) {{
    showToast('请先勾选要操作的产品');
    return;
  }}
  if (!confirm('确定将已选的 ' + checkboxes.length + ' 个产品的进度改为"' + newStage + '"吗？')) return;
  
  checkboxes.forEach(cb => {{
    const asin = cb.dataset.asin;
    const p = PRODUCTS.find(x => x.asin === asin);
    if (p) p._progress = newStage;
  }});
  
  // 取消全选
  document.getElementById('checkAllActive').checked = false;
  
  saveProgress();
  // 保留用户当前的"类目/标签/搜索"筛选，仅将进度筛选复位为"全部活跃"
  // 这样批量更改进度后仍停留在已筛选的类目下，且更新后的产品仍可见
  document.getElementById('filterProgress').value = 'all';
  // filterCategory / filterLabel / filterSearch 保持不变
  renderAll();
  applyFilters();
  refreshCharts();
  updateStats();
  updateAbandonedBadge();
  updateSelectedCount();
  showToast('✅ 已更新 ' + checkboxes.length + ' 个产品 → ' + newStage);
}}

// ===== 上下移动按钮 =====
function moveRow(e, asin, direction) {{
  e.stopPropagation();
  const idx = PRODUCTS.findIndex(p => p.asin === asin);
  if (idx === -1) return;
  
  const newIdx = idx + direction;
  if (newIdx < 0 || newIdx >= PRODUCTS.length) return;
  
  const [moved] = PRODUCTS.splice(idx, 1);
  PRODUCTS.splice(newIdx, 0, moved);
  
  saveOrder();
  renderAll();
  applyFilters();
}}

// ===== 更新进度 =====
function updateProgress(asin, newStage) {{
  const p = PRODUCTS.find(x => x.asin === asin);
  if (!p) return;
  
  const oldStage = p._progress;
  p._progress = newStage;
  saveProgress();
  
  // 如果变为放弃/已合作，或从放弃/已合作恢复，需要完整重渲染（在池之间迁移）
  if (oldStage === '放弃' || newStage === '放弃' || oldStage === '已合作' || newStage === '已合作') {{
    renderAll();
    refreshCharts();
    applyFilters();
  }} else {{
    // 仅更新当前行的下拉框样式
    const rows = document.querySelectorAll(`tr[data-asin="${{asin}}"]`);
    rows.forEach(row => {{
      const sel = row.querySelector('.progress-select');
      if (sel) sel.className = 'progress-select stage-' + newStage;
      row.dataset.progress = newStage;
    }});
    refreshCharts();
    updateStats();
  }}
  
  updateAbandonedBadge();
  updateCooperatedBadge();
  showToast('进度已更新: ' + newStage);
}}

// ===== 放弃产品池折叠 =====
function toggleAbandoned(forceOpen) {{
  const body = document.getElementById('abandonedBody');
  const arrow = document.getElementById('abandonedArrow');
  const isOpen = body.classList.contains('open');
  
  if (forceOpen === true) {{
    body.classList.add('open');
    arrow.classList.add('open');
  }} else if (forceOpen === false) {{
    body.classList.remove('open');
    arrow.classList.remove('open');
  }} else {{
    body.classList.toggle('open');
    arrow.classList.toggle('open');
  }}
}}

function updateAbandonedBadge() {{
  const count = getAbandoned().length;
  document.getElementById('abandonedBadge').textContent = count;
}}

function updateCooperatedBadge() {{
  const count = getCooperated().length;
  document.getElementById('cooperatedBadge').textContent = count;
}}

// ===== 已合作产品池折叠 =====
function toggleCooperated(forceOpen) {{
  const body = document.getElementById('cooperatedBody');
  const arrow = document.getElementById('cooperatedArrow');
  if (forceOpen === true) {{
    body.classList.add('open');
    arrow.classList.add('open');
  }} else if (forceOpen === false) {{
    body.classList.remove('open');
    arrow.classList.remove('open');
  }} else {{
    body.classList.toggle('open');
    arrow.classList.toggle('open');
  }}
}}

// ===== 筛选 =====
function applyFilters() {{
  const fp = document.getElementById('filterProgress').value;
  const fc = document.getElementById('filterCategory').value;
  const ft = document.getElementById('filterTracker').value;
  const fs = document.getElementById('filterSearch').value.toLowerCase();
  
  let active = getActive();
  
  if (fp !== 'all') {{
    if (fp === '放弃') {{
      active = [];
      toggleAbandoned(true);
    }} else if (fp === '已合作') {{
      active = [];
      toggleCooperated(true);
    }} else {{
      active = active.filter(p => p._progress === fp);
    }}
  }}
  if (fc !== 'all') active = active.filter(p =>
    fc === '其他' ? catShortOf(p.category) === '其他' : (p.category || '其他') === fc);
  if (ft !== 'all') active = active.filter(p => (p._tracker || '').trim() === ft);
  if (fs) active = active.filter(p => 
    (p.asin || '').toLowerCase().includes(fs) ||
    (p.brand || '').toLowerCase().includes(fs) ||
    (p.title || '').toLowerCase().includes(fs)
  );
  
  renderActiveTable(active);
}}

function quickFilter(stage) {{
  if (stage === 'all') {{
    document.getElementById('filterProgress').value = 'all';
    applyFilters();
  }} else if (stage === '放弃') {{
    toggleAbandoned(true);
    document.getElementById('abandonedSection').scrollIntoView({{behavior:'smooth'}});
  }} else if (stage === '已合作') {{
    toggleCooperated(true);
    document.getElementById('cooperatedSection').scrollIntoView({{behavior:'smooth'}});
  }} else {{
    document.getElementById('filterProgress').value = stage;
    applyFilters();
  }}
}}

// ===== 类目 / 追踪人筛选下拉：自动抓取看板数据中出现的全部值 =====
function refreshToolbarFilters() {{
  // 类目下拉：所有非空 category 去重 +「其他」（空/未识别类目归其他）
  const cs = document.getElementById('filterCategory');
  if (cs) {{
    const cur = cs.value;
    const cats = new Set();
    let hasOther = false;
    PRODUCTS.forEach(p => {{
      const c = (p.category || '').trim();
      if (c) cats.add(c); else hasOther = true;
    }});
    let opts = '<option value="all">全部类目</option>';
    [...cats].sort((a, b) => {{
      const wa = FULL2SHORT[a] ? 0 : 1, wb = FULL2SHORT[b] ? 0 : 1;
      if (wa !== wb) return wa - wb;             // 四大类在前
      const ia = Object.values(FULL2SHORT).indexOf(FULL2SHORT[a]);
      const ib = Object.values(FULL2SHORT).indexOf(FULL2SHORT[b]);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    }}).forEach(c => {{ opts += '<option value="' + escHtml(c) + '">' + escHtml(c) + '</option>'; }});
    if (hasOther) opts += '<option value="其他">其他</option>';
    cs.innerHTML = opts;
    if (cur && [...cs.options].some(o => o.value === cur)) cs.value = cur;
  }}
  // 追踪人下拉：所有 _tracker 去重
  const ts = document.getElementById('filterTracker');
  if (ts) {{
    const cur = ts.value;
    const trackers = [...new Set(PRODUCTS.map(p => (p._tracker || '').trim()).filter(Boolean))].sort();
    let opts = '<option value="all">全部追踪人</option>';
    trackers.forEach(t => {{ opts += '<option value="' + escHtml(t) + '">' + escHtml(t) + '</option>'; }});
    ts.innerHTML = opts;
    if (cur && [...ts.options].some(o => o.value === cur)) ts.value = cur;
  }}
}}

// ===== 图表 =====
let chartInstances = {{}};

// ===== 进度分布图表：5 类（其他/Automotive/ArtsCrafts/PatioLawn/ToolsHome）× 4 进行中进度（横向堆叠条形）=====
const BAR_CATS = ['其他', 'Automotive', 'ArtsCrafts', 'PatioLawn', 'ToolsHome'];
const BAR_STAGES = ['待调研', '调研中', '已联系', '已送样'];
const BAR_COLORS = ['#6c757d', '#0d6efd', '#fd7e14', '#198754'];
const FULL2SHORT = {{ 'Arts, Crafts & Sewing': 'ArtsCrafts', 'Automotive': 'Automotive', 'Patio, Lawn & Garden': 'PatioLawn', 'Tools & Home Improvement': 'ToolsHome' }};
function catShortOf(c) {{ return FULL2SHORT[c] || '其他'; }}
function buildProgressBarData() {{
  const active = PRODUCTS.filter(p => BAR_STAGES.indexOf(p._progress) >= 0);
  const datasets = BAR_STAGES.map((s, si) => ({{
    label: s,
    data: BAR_CATS.map(c => active.filter(p => catShortOf(p.category) === c && p._progress === s).length),
    backgroundColor: BAR_COLORS[si],
    borderWidth: 0,
  }}));
  return {{ labels: BAR_CATS, datasets: datasets }};
}}

// 点击条形图色块 -> 筛选下方产品：该类目 + 该进度
function onProgressBarClick(evt, item) {{
  if (!item || !item.length) return;
  const i = item[0];
  if (i.index === undefined || i.datasetIndex === undefined) return;
  const catShort = BAR_CATS[i.index];                 // 短名（其他/Automotive/...）
  const stage = BAR_STAGES[i.datasetIndex];           // 进度（待调研/...）
  const full = (Object.keys(FULL2SHORT).find(k => FULL2SHORT[k] === catShort)) || '其他';
  const fc = document.getElementById('filterCategory');
  const fp = document.getElementById('filterProgress');
  if (fc) fc.value = full;
  if (fp) fp.value = stage;
  // 收起放弃/已合作区，只展示进行中产品
  try {{
    if (typeof toggleCooperated === 'function') toggleCooperated(false);
    if (typeof toggleAbandoned === 'function') toggleAbandoned(false);
  }} catch (e) {{}}
  applyFilters();
  const wrap = document.getElementById('activeTableWrap');
  if (wrap) wrap.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
}}

function renderCharts() {{
  // 1) 进度分布：横向堆叠条形（5 类 × 4 进行中进度）
  const pb = buildProgressBarData();
  if (chartInstances['chartProgress']) chartInstances['chartProgress'].destroy();
  const ctxP = document.getElementById('chartProgress').getContext('2d');
  chartInstances['chartProgress'] = new Chart(ctxP, {{
    type: 'bar',
    data: {{ labels: pb.labels, datasets: pb.datasets }},
    options: {{
      indexAxis: 'y', responsive: true, maintainAspectRatio: true,
      onClick: onProgressBarClick,
      scales: {{ x: {{ stacked: true, beginAtZero: true, ticks: {{ font: {{ size: 10 }} }} }}, y: {{ stacked: true, ticks: {{ font: {{ size: 10 }} }} }} }},
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }}, padding: 12, usePointStyle: true }} }},
        datalabels: {{ color: '#fff', anchor: 'center', align: 'center', font: {{ size: 10, weight: 'bold' }}, formatter: (v) => v > 0 ? v : '' }}
      }}
    }}
  }});
  // 2) 类目分布：环形（保留）
  const catMap = {{}};
  PRODUCTS.forEach(p => {{ const c = CATEGORY_SHORT[p.category] || p.category || '其他'; catMap[c] = (catMap[c] || 0) + 1; }});
  if (chartInstances['chartCategory']) chartInstances['chartCategory'].destroy();
  const ctxC = document.getElementById('chartCategory').getContext('2d');
  chartInstances['chartCategory'] = new Chart(ctxC, {{
    type: 'doughnut',
    data: {{ labels: Object.keys(catMap), datasets: [{{ data: Object.values(catMap), backgroundColor: ['#2F5496', '#5b8ec4', '#8ecae6', '#219ebc', '#023047'], borderWidth: 0 }}] }},
    options: {{ responsive: true, maintainAspectRatio: true, plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }}, padding: 12, usePointStyle: true }} }}, datalabels: {{ display: false }} }} }}
  }});
  // 初始化/重建图表时同步刷新顶部统计，确保与加载到的进度（localStorage/服务器）一致
  updateStats();
}}

function refreshCharts() {{
  // 先刷新顶部统计，保证不因图表渲染异常而遗漏
  updateStats();
  try {{
    const pb = buildProgressBarData();
    const cpi = chartInstances['chartProgress'];
    if (cpi) {{
      cpi.data.labels = pb.labels;
      cpi.data.datasets = pb.datasets;
      cpi.update();
    }}
    const catMap = {{}};
    PRODUCTS.forEach(p => {{ const c = CATEGORY_SHORT[p.category] || p.category || '其他'; catMap[c] = (catMap[c] || 0) + 1; }});
    const cci = chartInstances['chartCategory'];
    if (cci) {{
      cci.data.labels = Object.keys(catMap);
      cci.data.datasets[0].data = Object.values(catMap);
      cci.update();
    }}
  }} catch (e) {{}}
}}

function updateStats() {{
  const byProgress = {{}};
  PRODUCTS.forEach(p => {{ byProgress[p._progress] = (byProgress[p._progress] || 0) + 1; }});
  const active = PRODUCTS.filter(p => p._progress !== '放弃' && p._progress !== '已合作').length;
  
  document.getElementById('statTotal').textContent = PRODUCTS.length;
  document.getElementById('statPending').textContent = byProgress['待调研'] || 0;
  document.getElementById('statResearching').textContent = byProgress['调研中'] || 0;
  document.getElementById('statContacted').textContent = byProgress['已联系'] || 0;
  document.getElementById('statSample').textContent = byProgress['已送样'] || 0;
  document.getElementById('statDone').textContent = byProgress['已合作'] || 0;
  document.getElementById('statAbandoned').textContent = byProgress['放弃'] || 0;
  // 更新第8个卡片（进行中）
  const cards = document.querySelectorAll('.stat-card .num');
  if (cards.length >= 8) cards[7].textContent = active;
  updateCooperatedBadge();
}}

// ===== 导出 CSV =====
function exportCSV() {{
  const active = getActive();
  const cooperated = getCooperated();
  const abandoned = getAbandoned();
  
  const headers = ['类目','ASIN','品牌','标题','中文简介','标签','来源','当前进度','近30天销量','月销售额','售价','上架时间','评分','评论数','BSR排名','变体数','卖家','主图链接'];
  
  function toRows(products) {{
    return products.map(p => [
      p.category || '', p.asin, p.brand || '', p.title || '', p._title_cn || '',
      p.__label__ || '', p._source || '', p._progress || '',
      p.sales || '', p.monthly_sales || '', p.price || '', p.available || '',
      p.rating || '', p.reviews || '', p.bsr || '', p.variants || '',
      p.seller || '', p.image || ''
    ]);
  }}
  
  const allRows = [...toRows(active), ...toRows(cooperated), ...toRows(abandoned)];
  
  let csv = '\\uFEFF' + headers.join(',') + '\\n';
  allRows.forEach(r => csv += r.map(v => '"' + (v || '').replace(/"/g, '""') + '"').join(',') + '\\n');
  
  const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'DuraTech_产品追踪_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click(); URL.revokeObjectURL(url);
  showToast('已导出 ' + (active.length + cooperated.length + abandoned.length) + ' 条');
}}

// ===== 导入 JSON =====
function importJSON(input) {{
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {{
    try {{
      const data = JSON.parse(e.target.result);
      const newProducts = data.products || [];
      let added = 0, updated = 0;
      newProducts.forEach(np => {{
        const existing = PRODUCTS.find(p => p.asin === np.asin);
        if (existing) {{ Object.assign(existing, np); updated++; }}
        else {{ np._progress = '待调研'; np._source = data.type || 'imported'; PRODUCTS.push(np); added++; }}
      }});
      saveProgress(); saveOrder();
      renderAll(); refreshCharts();
      showToast('导入完成: 新增 ' + added + ' 条, 更新 ' + updated + ' 条');
    }} catch(err) {{ showToast('导入失败: ' + err.message); }}
  }};
  reader.readAsText(file);
  input.value = '';
}}

// ===== 导出/导入进度备份 =====
function exportProgress() {{
  const data = {{}};
  PRODUCTS.forEach(p => {{ data[p.asin] = p._progress; }});
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], {{ type: 'application/json;charset=utf-8' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'progress_backup_' + new Date().toISOString().slice(0,10) + '.json';
  a.click();
  URL.revokeObjectURL(url);
  // 同时写入 localStorage 双保险
  saveProgress();
  showToast('已导出进度备份 (' + PRODUCTS.length + ' 条)，请把文件放到工作目录以持久化');
}}

function importProgress(input) {{
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {{
    try {{
      const data = JSON.parse(e.target.result);
      let applied = 0;
      PRODUCTS.forEach(p => {{
        if (data[p.asin]) {{ p._progress = data[p.asin]; applied++; }}
      }});
      saveProgress();
      renderAll();
      applyFilters();
      refreshCharts();
      showToast('进度已恢复: ' + applied + ' 条');
    }} catch(err) {{ showToast('导入失败: ' + err.message); }}
  }};
  reader.readAsText(file);
  input.value = '';
}}

// ===== 重置排序 =====
function resetAll() {{
  if (!confirm('确定要重置排序吗？（进度不会丢失）')) return;
  PRODUCTS.sort((a, b) => {{
    if (a._source !== b._source) return a._source === 'new' ? -1 : 1;
    const sa = parseInt(a.sales) || 0;
    const sb = parseInt(b.sales) || 0;
    return sb - sa;
  }});
  saveOrder();
  renderAll();
  applyFilters();
  showToast('排序已重置（新品优先，按销量降序）');
}}

// ===== 工具 =====

// ===== 类目排序（按四大类顺序升/降序） =====
const CATEGORY_ORDER = ['Arts, Crafts & Sewing','Automotive','Patio, Lawn & Garden','Tools & Home Improvement'];
let categorySortDir = -1; // 初始 -1，首次点击后变为 1（升序=四大类顺序）
function categoryWeight(c) {{
  const i = CATEGORY_ORDER.indexOf(c);
  return i === -1 ? CATEGORY_ORDER.length : i;
}}
function sortByCategory() {{
  categorySortDir = -categorySortDir;
  PRODUCTS.sort((a, b) => {{
    const va = categoryWeight(a.category), vb = categoryWeight(b.category);
    const ua = va >= CATEGORY_ORDER.length, ub = vb >= CATEGORY_ORDER.length;
    if (ua !== ub) return ua ? 1 : -1;  // 未知/空类目始终排最后
    const d = (va - vb) * categorySortDir;
    if (d !== 0) return d;
    return (parseInt(b.sales) || 0) - (parseInt(a.sales) || 0); // 同类内按销量降序
  }});
  renderAll();
  applyFilters();
  showToast(categorySortDir === 1 ? '已按四大类顺序升序排序' : '已按四大类顺序降序排序');
  saveOrder();
}}

// ===== 市场分析附件（前端原型：上传/列表接口后续接入后端） =====
let marketCurrentAsin = '';
function openMarketModal(asin) {{
  marketCurrentAsin = asin;
  document.getElementById('marketAsin').textContent = asin;
  document.getElementById('marketModal').style.display = 'flex';
  document.getElementById('marketMsg').textContent = '';
  document.getElementById('marketFileInput').value = '';
  loadMarketFiles(asin);
}}
function closeMarketModal() {{
  document.getElementById('marketModal').style.display = 'none';
}}
async function loadMarketFiles(asin) {{
  const box = document.getElementById('marketList');
  box.innerHTML = '<div style="color:#bbb;text-align:center;padding:20px">加载中…</div>';
  try {{
    const t = getTok();
    const resp = await fetch('/api/market/list?asin=' + encodeURIComponent(asin), {{
      headers: {{ 'Authorization': 'Bearer ' + t }}
    }});
    const d = await resp.json().catch(() => ({{ ok: false, error: '响应解析失败' }}));
    if (!d.ok) {{ box.innerHTML = '<div style="color:#dc3545">' + (d.error || '加载失败') + '</div>'; return; }}
    const files = d.files || [];
    const cnt = document.getElementById('mktcnt_' + asin);
    if (cnt) cnt.textContent = files.length;
    if (!files.length) {{
      box.innerHTML = '<div style="color:#bbb;text-align:center;padding:20px">（暂无附件，可上传 HTML / Excel）</div>';
      return;
    }}
    box.innerHTML = files.map(f => {{
      const href = '/api/market/file/' + encodeURIComponent(asin) + '/' + encodeURIComponent(f.name);
      const kb = (f.size / 1024).toFixed(1);
      return '<div style="display:flex;align-items:center;justify-content:space-between;padding:7px 4px;border-bottom:1px solid #f0f0f0;gap:8px">'
        + '<a href="' + href + '" target="_blank" rel="noopener" title="新标签页打开" style="color:#2F5496;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">📄 ' + f.name + '</a>'
        + '<span style="color:#999;font-size:11px;white-space:nowrap">' + kb + ' KB · ' + f.mtime + '</span>'
        + '</div>';
    }}).join('');
  }} catch (e) {{
    box.innerHTML = '<div style="color:#dc3545">加载失败: ' + e.message + '</div>';
  }}
}}
// 批量刷新当前所有行的市场分析附件计数（排序/渲染后调用，避免归 0）
async function loadMarketCounts() {{
  try {{
    const rows = document.querySelectorAll('tbody tr[data-asin]');
    const asins = [...rows].map(tr => tr.dataset.asin).filter(Boolean);
    if (!asins.length) return;
    const t = getTok();
    const resp = await fetch('/api/market/counts?asins=' + encodeURIComponent(asins.join(',')), {{
      headers: {{ 'Authorization': 'Bearer ' + t }}
    }});
    const d = await resp.json().catch(() => ({{ ok: false, error: 'fail' }}));
    if (!d.ok || !d.counts) return;
    Object.keys(d.counts).forEach(a => {{
      const el = document.getElementById('mktcnt_' + a);
      if (el) el.textContent = d.counts[a];
    }});
  }} catch (e) {{ /* 忽略：后端未就绪时保持初始值 */ }}
}}
async function uploadMarketFile() {{
  const msg = document.getElementById('marketMsg');
  const inp = document.getElementById('marketFileInput');
  if (!marketCurrentAsin) {{ msg.textContent = '❌ 缺少 ASIN'; msg.style.color = '#dc3545'; return; }}
  if (!inp.files || !inp.files.length) {{ msg.textContent = '请先选择文件'; msg.style.color = '#dc3545'; return; }}
  const fd = new FormData();
  fd.append('asin', marketCurrentAsin);
  for (const f of inp.files) fd.append('files', f);
  const t = getTok();
  msg.textContent = '⏳ 上传中…'; msg.style.color = '#666';
  try {{
    const resp = await fetch('/api/market/upload', {{
      method: 'POST', headers: {{ 'Authorization': 'Bearer ' + t }}, body: fd
    }});
    const d = await resp.json().catch(() => ({{ ok: false, error: '响应解析失败' }}));
    if (!d.ok) {{ msg.textContent = '❌ ' + (d.error || '上传失败'); msg.style.color = '#dc3545'; return; }}
    msg.textContent = '✅ ' + (d.message || '上传成功'); msg.style.color = '#198754';
    inp.value = '';
    loadMarketFiles(marketCurrentAsin);
  }} catch (e) {{
    msg.textContent = '❌ 网络错误: ' + e.message; msg.style.color = '#dc3545';
  }}
}}

// ===== 查竞品页面数据变化标注（销量/月销额/售价/BSR 列下方小字） =====
// 数据全部来自卖家精灵「查竞品」结果各指标卡：
//   sales_pct / monthly_pct / price_pct：各卡 text-muted 环比（'-' 表示无变化 -> 空）
//   bsr_delta / bsr_pct：BSR 卡较上月变化量/百分比
function deltaNote(p, kind) {{
  let tip = '';
  if (kind === 'sales') tip = '近30天销量环比（卖家精灵）';
  else if (kind === 'monthly') tip = '月销售额环比（卖家精灵）';
  else if (kind === 'price') tip = '售价变化（卖家精灵）';
  else if (kind === 'bsr') tip = 'BSR 较上月变化（卖家精灵）';

  if (kind === 'bsr') {{
    const d = p.bsr_delta, pc = p.bsr_pct;
    if (d === undefined || d === null || d === '' || isNaN(parseFloat(d))) return '';
    const dn = parseFloat(d);
    if (dn === 0) return '';
    const arrow = dn > 0 ? '▲' : '▼';
    const pct = (pc !== undefined && pc !== null && pc !== '' && !isNaN(parseFloat(pc)))
                ? ' / ' + Math.abs(parseFloat(pc)) + '%' : '';
    return '<div class="cell-delta" title="' + tip + '"><span class="delta-bsr">' + arrow + ' ' +
           Math.abs(dn).toLocaleString('en-US') + pct + '</span></div>';
  }}

  const pct = (kind === 'sales') ? p.sales_pct : (kind === 'monthly') ? p.monthly_pct : p.price_pct;
  if (pct === undefined || pct === null || pct === '' || isNaN(parseFloat(pct))) return '';
  const n = parseFloat(pct);
  const arrow = n > 0 ? '▲' : (n < 0 ? '▼' : '＝');
  const cls = n > 0 ? 'delta-up' : (n < 0 ? 'delta-down' : 'delta-flat');
  return '<div class="cell-delta" title="' + tip + '"><span class="' + cls + '">' + arrow + ' ' +
         Math.abs(n) + '%</span></div>';
}}

// ===== 手动添加 ASIN（调 /api/tracking/add） =====
function openAddAsinModal() {{
  const m = document.getElementById('addAsinModal');
  if (m) m.style.display = 'flex';
  const msg = document.getElementById('addAsinMsg');
  if (msg) msg.textContent = '';
  const inp = document.getElementById('addAsinInput');
  if (inp) inp.value = '';
  setTimeout(() => {{ const i = document.getElementById('addAsinInput'); if (i) i.focus(); }}, 100);
}}
function closeAddAsinModal() {{
  const m = document.getElementById('addAsinModal');
  if (m) m.style.display = 'none';
}}
async function checkCookie() {{
  try {{
    const t = getTok();
    const resp = await fetch('/api/cookie/check', {{ headers: {{ 'Authorization': 'Bearer ' + t }} }});
    const d = await resp.json().catch(() => ({{ valid: false }}));
    return !!d.valid;
  }} catch (e) {{ return false; }}
}}

async function apiPostJson(url, body) {{
  const t = getTok();
  const resp = await fetch(url, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + t }},
    body: JSON.stringify(body || {{}})
  }});
  return await resp.json().catch(() => ({{ ok: false, error: '响应解析失败' }}));
}}

function hideUploadShowProgress() {{
  const ua = document.getElementById('lookupUploadArea');
  if (ua) ua.style.display = 'none';
  const panel = document.getElementById('lookupPanel');
  if (panel) panel.style.display = 'block';
}}

// 「产品信息更新」：先检测 Cookie，有效直接开始，过期弹上传
async function startUpdateOrUpload() {{
  openLookupCard('update');
  const valid = await checkCookie();
  if (valid) {{
    hideUploadShowProgress();
    const d = await apiPostJson('/api/tracking/update/start', {{}});
    if (!d.ok) {{ showToast('❌ ' + (d.error || '启动失败')); return; }}
    showToast(d.message || '产品信息更新已开始');
    startLuPolling();
  }} else {{
    showToast('⚠️ Cookie 已过期，请上传最新 Cookie');
  }}
}}

async function doAddAsin() {{
  const inp = document.getElementById('addAsinInput');
  const msg = document.getElementById('addAsinMsg');
  if (!inp || !msg) return;
  const asin = (inp.value || '').trim().toUpperCase();
  if (!asin) {{ msg.textContent = '请输入 ASIN'; msg.style.color = '#dc3545'; return; }}
  if (!/^[A-Z0-9]{{8,12}}$/.test(asin)) {{ msg.textContent = '❌ ASIN 格式不正确（8-12 位字母数字）'; msg.style.color = '#dc3545'; return; }}
  msg.textContent = '⏳ 检查 ASIN 是否已存在…';
  msg.style.color = '#666';
  try {{
    const t = getTok();
    const resp = await fetch('/api/tracking/exists?asin=' + encodeURIComponent(asin), {{
      headers: {{ 'Authorization': 'Bearer ' + t }}
    }});
    const d = await resp.json().catch(() => ({{ ok: false, error: '响应解析失败' }}));
    if (!d.ok) {{ msg.textContent = '❌ ' + (d.error || '检查失败'); msg.style.color = '#dc3545'; return; }}
    if (d.exists) {{ msg.textContent = '❌ 该 ASIN 已在追踪看板中'; msg.style.color = '#dc3545'; return; }}
    // 通过预检：先检测 Cookie，有效直接开始抓取，过期弹上传
    closeAddAsinModal();
    openLookupCard('add', asin);
    const valid = await checkCookie();
    if (valid) {{
      hideUploadShowProgress();
      const r2 = await apiPostJson('/api/tracking/add/start', {{ asin: asin }});
      if (!r2.ok) {{ showToast('❌ ' + (r2.error || '添加失败')); return; }}
      showToast(r2.message || '已开始添加');
      startLuPolling();
    }} else {{
      showToast('⚠️ Cookie 已过期，请上传最新 Cookie');
    }}
  }} catch (e) {{
    msg.textContent = '❌ 网络错误: ' + e.message;
    msg.style.color = '#dc3545';
  }}
}}

// ===== 卖家精灵 Cookie 上传 + 任务进度（产品信息更新 / 手动添加共用） =====
// 流程与需求池看板一致：上传 Cookie -> 服务端保存并启动任务 -> 轮询 /api/collection/status
let lookupCtx = {{ mode: 'update', asin: '' }};
let LuPollTimer = null;

function openLookupCard(mode, asin) {{
  lookupCtx = {{ mode: mode || 'update', asin: (asin || '').trim().toUpperCase() }};
  const card = document.getElementById('lookupCard');
  const title = document.getElementById('lookupCardTitle');
  const hint = document.getElementById('lookupHint');
  const f = document.getElementById('lookupCookieFile');
  const txt = document.getElementById('lookupCookieText');
  if (f) f.value = '';
  if (txt) txt.value = '';
  const panel = document.getElementById('lookupPanel');
  if (panel) panel.style.display = 'none';
  const ua = document.getElementById('lookupUploadArea');
  if (ua) ua.style.display = 'block';   // 默认显示上传区（Cookie 有效时再隐藏）
  if (title) title.textContent = mode === 'add' ? '🍪 添加产品 · 上传 Cookie' : '🍪 产品信息更新 · 上传 Cookie';
  if (hint) hint.textContent = mode === 'add'
    ? ('将用卖家精灵「查竞品」获取 <b>' + asin + '</b> 的产品信息并加入追踪看板（待调研）')
    : ('将批量更新全部「进行中」产品的最新销量/月销额/售价/BSR（已合作/放弃不更新），约 1-2 分钟');
  if (card) card.style.display = 'block';
  stopLuPolling();
}}
function closeLookupCard() {{
  if (LuPollTimer) {{ showToast('任务进行中，完成后自动刷新，请勿关闭'); return; }}
  const card = document.getElementById('lookupCard');
  if (card) card.style.display = 'none';
}}

async function uploadLookupCookie() {{
  const fileInput = document.getElementById('lookupCookieFile');
  const text = document.getElementById('lookupCookieText').value.trim();
  if ((!fileInput.files || !fileInput.files[0]) && !text) {{
    showToast('请选择 Cookie 文件或粘贴 JSON 文本'); return;
  }}
  const fd = new FormData();
  if (fileInput.files && fileInput.files[0]) fd.append('file', fileInput.files[0]);
  else fd.append('cookie_text', text);
  fd.append('task', lookupCtx.mode === 'add' ? 'lookup_add' : 'lookup_update');
  if (lookupCtx.mode === 'add') fd.append('asin', lookupCtx.asin);
  const t = getTok();
  showToast('⏳ 上传 Cookie 中，请稍候…');
  try {{
    const resp = await fetch('/api/cookie', {{
      method: 'POST',
      headers: t ? {{ 'Authorization': 'Bearer ' + t }} : {{}},
      body: fd
    }});
    const d = await resp.json().catch(() => ({{ ok: false, error: '响应解析失败' }}));
    if (resp.status === 401) {{ showToast('登录已过期，请重新登录'); return; }}
    if (!d.ok) {{ showToast('❌ ' + (d.error || '上传失败')); return; }}
    showToast(d.message || 'Cookie 已保存，任务已开始');
    const panel = document.getElementById('lookupPanel');
    if (panel) panel.style.display = 'block';
    startLuPolling();
  }} catch (e) {{ showToast('❌ 网络错误: ' + e.message); }}
}}

async function LuFetchStatus() {{
  const t = getTok();
  const headers = {{}};
  if (t) headers['Authorization'] = 'Bearer ' + t;
  const resp = await fetch('/api/collection/status', {{ headers }});
  return await resp.json().catch(() => ({{}}));
}}
function startLuPolling() {{
  stopLuPolling();
  LuPollTimer = setInterval(async () => {{
    try {{
      const d = await LuFetchStatus();
      renderLuStatus(d);
      if (d.state === 'done') {{
        stopLuPolling();
        if (d.task_type === 'lookup_update') {{
          showToast('✅ 产品信息更新完成：成功 ' + ((d.result && d.result.updated) || 0) + ' / 失败 ' + ((d.result && d.result.failed) || 0));
        }} else {{
          showToast('✅ ' + ((d.result && d.result.added) ? ('已添加 ' + d.result.added) : '添加完成'));
        }}
        setTimeout(() => location.reload(), 1500);
      }} else if (d.state === 'error') {{
        stopLuPolling();
        showToast('❌ ' + (d.error || '任务失败'));
      }}
    }} catch (e) {{ /* ignore */ }}
  }}, 3000);
  LuPollNow();
}}
async function LuPollNow() {{
  try {{ const d = await LuFetchStatus(); renderLuStatus(d); }} catch (e) {{}}
}}
function stopLuPolling() {{ if (LuPollTimer) {{ clearInterval(LuPollTimer); LuPollTimer = null; }} }}
function renderLuStatus(d) {{
  const bar = document.getElementById('luBar');
  const label = document.getElementById('luLabel');
  const step = document.getElementById('luStep');
  const pct = document.getElementById('luPct');
  const log = document.getElementById('luLog');
  const map = {{
    prepare: '准备中',
    fetch: d.task_type === 'lookup_update' ? '查竞品批量更新中' : '获取产品信息中',
    save: '写入商品库',
    build: '重建追踪看板',
    done: '完成',
    error: '失败'
  }};
  const p = d.progress || 0;
  const stepName = map[d.step] || d.step || '处理中…';
  if (bar) bar.style.width = p + '%';
  if (step) step.textContent = stepName;
  if (pct) pct.textContent = p + '%';
  if (label) label.textContent = stepName + ' · ' + p + '%' + (d.state === 'error' ? ' · 失败' : (d.state === 'done' ? ' · 已完成' : ''));
  if (log && d.logs) log.textContent = d.logs.slice(-600);
  if (bar) {{
    if (d.state === 'error') bar.style.background = '#dc3545';
    else if (d.state === 'done') bar.style.background = '#28a745';
    else bar.style.background = 'linear-gradient(90deg,#2F5496,#28a745)';
  }}
}}

function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 2000);
}}

// ===== 进度文本框展开/收起（点击交互） =====
// 逻辑：
//   - 点击文本框（聚焦）→ 放大为 300×200 浮层
//   - 点击文本框外任意区域 → 缩小回初始尺寸
//   - 无 hover 展开/收起，避免鼠标边缘跳动
function scCollapseAll() {{
  document.querySelectorAll('.subcategory-input.expand').forEach(function(el) {{
    el.classList.remove('expand');
  }});
}}
// 聚焦（点击）→ 放大；并收起其他已展开的框（保证同时只有一个放大）
document.addEventListener('focus', function(e) {{
  const el = e.target;
  if (el && el.classList && el.classList.contains('subcategory-input')) {{
    document.querySelectorAll('.subcategory-input.expand').forEach(function(x) {{
      if (x !== el) x.classList.remove('expand');
    }});
    el.classList.add('expand');
  }}
}}, true);
// 点击文本框外任意区域 → 缩小（事件委托到 document）
// 注意：focus 展开（absolute 定位）会导致点击的 mouseup/click target 漂移成 TD，
// 因此用 mousedown（此时尚未展开、位置未变）记录按下点是否在文本框内，点击时结合判断。
let __mousedownInSubcat = false;
document.addEventListener('mousedown', function(e) {{
  __mousedownInSubcat = !!(e.target && e.target.closest && e.target.closest('.subcategory-input'));
}}, true);
document.addEventListener('click', function(e) {{
  const inside = (e.target && e.target.closest && e.target.closest('.subcategory-input')) || __mousedownInSubcat;
  __mousedownInSubcat = false;
  if (!inside) scCollapseAll();
}});

// ===== 页面缩放（自适应分辨率 / 缩放大小） =====
let currentZoom = parseFloat(localStorage.getItem('dt_zoom') || '1') || 1;
function applyZoom() {{
  document.documentElement.style.zoom = currentZoom;
  const z = document.getElementById('zoomVal');
  if (z) z.textContent = Math.round(currentZoom * 100) + '%';
}}
function zoomIn() {{ currentZoom = Math.min(1.8, Math.round((currentZoom + 0.1) * 10) / 10); localStorage.setItem('dt_zoom', currentZoom); applyZoom(); }}
function zoomOut() {{ currentZoom = Math.max(0.6, Math.round((currentZoom - 0.1) * 10) / 10); localStorage.setItem('dt_zoom', currentZoom); applyZoom(); }}
function zoomReset() {{ currentZoom = 1; localStorage.removeItem('dt_zoom'); applyZoom(); }}

// ===== 初始化 =====
(async function initBoard() {{
  loadProgress();
  loadOrder();
  loadSubcategories();
  await loadServerEdits();   // 服务端持久化编辑覆盖本地 localStorage
  _autosaveReady = true;
  renderAll();
  renderCharts();
  applyZoom();
}})();
</script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding='utf-8')
    print(f"[OK] 看板 v2 已生成: {output_path}")
    print(f"     产品总数: {total} (活跃: {active_count}, 放弃: {abandoned_count})")
    print(f"     新品: {new_count}, 爆品: {hot_count}")
    return output_path


if __name__ == '__main__':
    build_dashboard()
