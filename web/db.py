"""
DuraTech 看板 Web 版 - SQLite 数据层
存储产品基础数据（products 表）和进度/备注/排序（progress 表）
所有读写都走这里，前端通过 Flask API 调用。
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
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


def _ensure_column(conn, table, column, ddl):
    """幂等迁移：若表缺少指定列则 ALTER TABLE 添加（兼容旧 schema 升级）。"""
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return
    if column not in cols:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            print(f"  [MIGRATE] 表 {table} 已添加列 {column}")
        except Exception as e:
            print(f"  [WARN] 迁移 {table}.{column} 失败: {e}")


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
        tracker TEXT DEFAULT '',
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
    CREATE TABLE IF NOT EXISTS login_attempts (
        username TEXT PRIMARY KEY,
        fails INTEGER DEFAULT 0,
        locked_until TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_progress_stage ON progress(stage);
    """)

    # ---- 兼容旧 schema 的幂等迁移（老库无 tracker 列时自动 ALTER）----
    _ensure_column(conn, "progress", "tracker", "TEXT DEFAULT ''")

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
        p["_tracker"] = prog["tracker"] if prog else ""
        p["_order"] = prog["order_index"] if prog else 0
        products.append(p)

    products.sort(key=lambda x: (x.get("_order", 0), x.get("asin", "")))
    return products


def save_progress(updates):
    """批量保存进度/备注/追踪人/排序，updates=[{asin, stage, note, tracker, order}]"""
    conn = get_conn()
    now = datetime.now()
    n = 0
    for u in updates:
        asin = u.get("asin")
        if not asin:
            continue
        stage = u.get("stage")
        note = u.get("note")
        tracker = u.get("tracker")
        order = u.get("order")
        conn.execute(
            """INSERT INTO progress (asin, stage, note, tracker, order_index, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(asin) DO UPDATE SET
                 stage=COALESCE(?, stage),
                 note=COALESCE(?, note),
                 tracker=COALESCE(?, tracker),
                 order_index=COALESCE(?, order_index),
                 updated_at=?""",
            (asin, stage, note, tracker, order, now, stage, note, tracker, order, now)
        )
        n += 1
    conn.commit()
    conn.close()
    return n


def get_all_progress():
    """返回全量进度/备注/追踪人/排序，结构 {asin: {progress, subcategory, tracker, order}}。
    供追踪看板前端初始化时拉取服务端持久化的最新编辑（db 为权威源）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT asin, stage, note, tracker, order_index FROM progress").fetchall()
    conn.close()
    out = {}
    for r in rows:
        out[r["asin"]] = {
            "progress": r["stage"],
            "subcategory": r["note"] or "",
            "tracker": r["tracker"] or "",
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


# ============================================================
# 追踪看板 canonical 读写（手动添加 / 查竞品刷新共用）
# ============================================================

def load_transferred():
    """读取 canonical 追踪商品库（产品列表）；文件缺失/损坏返回 []"""
    if not CANONICAL.exists():
        return []
    try:
        data = json.loads(CANONICAL.read_text(encoding="utf-8"))
        return list(data.get("products", []) or [])
    except Exception as e:
        print(f"  [WARN] 读取 canonical 失败: {e}")
        return []


def save_transferred(products):
    """整体写回 canonical（追踪商品库唯一数据源）"""
    CANONICAL.parent.mkdir(parents=True, exist_ok=True)
    payload = {"products": products, "updated_at": datetime.now().isoformat()}
    CANONICAL.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def upsert_transferred(product):
    """按 ASIN 覆盖 canonical 中已存在产品，不存在则追加。

    覆盖时保留已有进度/追踪人/来源等状态字段（_progress/_tracker/_source/
    category 等），避免新数据把用户手工维护的字段清空。
    返回 (product, is_new)。
    """
    products = load_transferred()
    asin = product.get("asin", "")
    idx = next((i for i, p in enumerate(products)
                if p.get("asin", "").upper() == asin.upper()), None)
    is_new = idx is None
    if idx is None:
        products.append(product)
    else:
        old = products[idx]
        for k in ("_progress", "_subcategory", "_tracker", "_order",
                  "_source", "__label__", "category"):
            if k not in product and old.get(k) not in (None, ""):
                product[k] = old[k]
        products[idx] = product
    save_transferred(products)
    return product, is_new


# ============================================================
# 登录失败防护（防暴力破解）
# 连续失败 N 次锁定 M 分钟；SQLite 持久化，进程重启不丢，原子 UPSERT 多线程安全。
# ============================================================
MAX_FAILS = 5
LOCK_MINUTES = 15


def _now_iso():
    return datetime.now().isoformat()


def is_locked(username):
    """查询账号是否处于锁定状态；锁定过期则自动清零并返回 False"""
    if not username:
        return False
    conn = get_conn()
    row = conn.execute(
        "SELECT fails, locked_until FROM login_attempts WHERE username=?",
        (username,)).fetchone()
    conn.close()
    if not row:
        return False
    if row["locked_until"]:
        try:
            if datetime.fromisoformat(row["locked_until"]) > datetime.now():
                return True
        except Exception:
            return False
        # 锁定已过期：清零
        reset_fail(username)
    return False


def record_fail(username):
    """记录一次登录失败；达到阈值则锁定 LOCK_MINUTES 分钟。返回当前失败次数"""
    if not username:
        return 0
    now = datetime.now()
    lock_until = (now + timedelta(minutes=LOCK_MINUTES)).isoformat()
    conn = get_conn()
    conn.execute(
        """INSERT INTO login_attempts (username, fails, locked_until) VALUES (?, 1, '')
           ON CONFLICT(username) DO UPDATE SET
             fails = fails + 1,
             locked_until = CASE WHEN fails + 1 >= ? THEN ? ELSE '' END""",
        (username, MAX_FAILS, lock_until))
    conn.commit()
    row = conn.execute(
        "SELECT fails FROM login_attempts WHERE username=?", (username,)).fetchone()
    conn.close()
    return row["fails"] if row else 0


def reset_fail(username):
    """登录成功后清零失败计数与锁定"""
    if not username:
        return
    conn = get_conn()
    conn.execute("DELETE FROM login_attempts WHERE username=?", (username,))
    conn.commit()
    conn.close()
