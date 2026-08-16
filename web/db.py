"""
DuraTech 看板 Web 版 - SQLite 数据层
存储产品基础数据（products 表）和进度/备注/排序（progress 表）
所有读写都走这里，前端通过 Flask API 调用。
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

BASE = Path(__file__).parent
DB_PATH = BASE / "board.db"
UPLOADS = Path("/root/uploads")
PROGRESS_BACKUP = Path("/workspace/progress_backup.json")
OUTPUT_DIR = Path("/workspace/sellersprite-automation/output")
WEEKLY_DIR = OUTPUT_DIR / "weekly"
CANONICAL = OUTPUT_DIR / "transferred_products.json"
PENDING_TRANSFER = OUTPUT_DIR / "pending_transfer.json"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS products (
        asin TEXT PRIMARY KEY,
        data TEXT,
        source TEXT,
        label TEXT,
        category TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS progress (
        asin TEXT PRIMARY KEY,
        stage TEXT DEFAULT '待调研',
        note TEXT DEFAULT '',
        order_index INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_progress_stage ON progress(stage);
    """)
    conn.commit()
    conn.close()


def collect_uploads():
    """从 /root/uploads/*.json 收集卖家精灵导出的产品，返回 {asin: product}"""
    products = {}
    if not UPLOADS.exists():
        return products
    for f in sorted(UPLOADS.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            for p in data.get("products", []):
                asin = p.get("asin", "")
                if not asin:
                    continue
                if asin not in products:
                    p["_source"] = data.get("type", "unknown")
                    products[asin] = p
                else:
                    existing = products[asin]
                    existing.update(p)
        except Exception as e:
            print(f"  [WARN] 跳过 {f.name}: {e}")
    return products


def refresh_products():
    """从 uploads 刷新 products 表（保留 progress 不变）"""
    conn = get_conn()
    products = collect_uploads()
    now = datetime.now()
    for asin, p in products.items():
        conn.execute(
            "INSERT OR REPLACE INTO products (asin, data, source, label, category, updated_at) VALUES (?,?,?,?,?,?)",
            (asin, json.dumps(p, ensure_ascii=False), p.get("_source", ""),
             p.get("__label__", ""), p.get("category", ""), now)
        )
    conn.commit()
    conn.close()
    return len(products)


def load_progress_backup():
    """从 /workspace/progress_backup.json 导入进度（仅填充缺失项）"""
    if not PROGRESS_BACKUP.exists():
        return 0
    try:
        data = json.loads(PROGRESS_BACKUP.read_text())
    except Exception:
        return 0
    conn = get_conn()
    n = 0
    for asin, stage in data.items():
        cur = conn.execute("SELECT 1 FROM progress WHERE asin=?", (asin,)).fetchone()
        if not cur:
            conn.execute("INSERT INTO progress (asin, stage) VALUES (?,?)", (asin, stage))
            n += 1
    conn.commit()
    conn.close()
    return n


def get_board():
    """返回合并产品基础数据 + 进度/备注/排序的列表（按 order 排序）"""
    conn = get_conn()
    product_rows = conn.execute("SELECT asin, data FROM products").fetchall()
    progress_rows = {r["asin"]: r for r in conn.execute("SELECT * FROM progress").fetchall()}
    conn.close()

    products = []
    for r in product_rows:
        try:
            p = json.loads(r["data"])
        except Exception:
            continue
        prog = progress_rows.get(r["asin"])
        p["_progress"] = prog["stage"] if prog else "待调研"
        p["_subcategory"] = prog["note"] if prog else ""
        p["_order"] = prog["order_index"] if prog else 0
        products.append(p)

    products.sort(key=lambda x: (x.get("_order", 0), x.get("asin", "")))
    return products


def save_progress(updates):
    """批量保存进度/备注/排序，updates=[{asin, stage, note, order}]"""
    conn = get_conn()
    now = datetime.now()
    n = 0
    for u in updates:
        asin = u.get("asin")
        if not asin:
            continue
        stage = u.get("stage")
        note = u.get("note")
        order = u.get("order")
        conn.execute(
            """INSERT INTO progress (asin, stage, note, order_index, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(asin) DO UPDATE SET
                 stage=COALESCE(?, stage),
                 note=COALESCE(?, note),
                 order_index=COALESCE(?, order_index),
                 updated_at=?""",
            (asin, stage, note, order, now, stage, note, order, now)
        )
        n += 1
    conn.commit()
    conn.close()
    return n


def get_all_progress():
    """返回全量进度/备注/排序，结构 {asin: {progress, subcategory, order}}。
    供追踪看板前端初始化时拉取服务端持久化的最新编辑（db 为权威源）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT asin, stage, note, order_index FROM progress").fetchall()
    conn.close()
    out = {}
    for r in rows:
        out[r["asin"]] = {
            "progress": r["stage"],
            "subcategory": r["note"] or "",
            "order": r["order_index"] or 0,
        }
    return out


def compute_stats(products):
    by_progress = Counter(p.get("_progress", "待调研") for p in products)
    total = len(products)
    abandoned = by_progress.get("放弃", 0)
    return {
        "total": total,
        "by_progress": dict(by_progress),
        "active": total - abandoned,
    }


def get_stats():
    return compute_stats(get_board())


# ============================================================
# 需求池 / 导入辅助
# ============================================================

def load_latest_pool(pool_type):
    """读取最新的需求池 JSON：output/weekly/{type}_pool_*.json
    返回 {type, week, stats, products} 或 None"""
    if not WEEKLY_DIR.exists():
        return None
    pattern = f"{pool_type}_pool_*.json"
    candidates = sorted(WEEKLY_DIR.glob(pattern), reverse=True)
    if not candidates:
        return None
    try:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] 读取需求池失败 {candidates[0].name}: {e}")
        return None


def load_canonical_asins():
    """返回 canonical 商品库中已有的 ASIN 集合"""
    if not CANONICAL.exists():
        return set()
    try:
        data = json.loads(CANONICAL.read_text(encoding="utf-8"))
        return {p.get("asin", "") for p in data.get("products", []) if p.get("asin")}
    except Exception:
        return set()


def write_pending_transfer(pool, products):
    """把勾选产品写入 output/pending_transfer.json（dashboard_builder 消费后删除）"""
    PENDING_TRANSFER.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pool": pool,
        "products": products,
        "transfer_time": datetime.now().isoformat(),
    }
    PENDING_TRANSFER.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return PENDING_TRANSFER
