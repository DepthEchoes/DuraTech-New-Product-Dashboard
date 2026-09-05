"""
DuraTech 需求池看板在线版 - 任务管理器
后台 daemon 线程顺序执行；全局状态机: task_type / state / step / progress / logs / error / result

任务类型：
  - collect        需求池采集：新品 → 爆品 → 周环比去重 → 重建需求池看板
  - lookup_update  查竞品批量更新：刷新追踪看板全部「进行中」产品的销量/月销额/售价/BSR
  - lookup_add     查竞品单 ASIN 添加：抓取信息后加入追踪看板（待调研）

import_lock：串行化对 dashboard_builder 的调用（防并发文件竞争）
"""
import io
import sys
import threading
import traceback
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
WEB_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(WEB_DIR))

import collector
import weekly_diff
import pool_builder
import dashboard_builder
import db as db_mod

POOL_HTML = WEB_DIR / "pool.html"
TRACKING_HTML = WEB_DIR / "board.html"
LOG_LIMIT = 4000

# 追踪看板「进行中」阶段（可被查竞品更新；已合作/放弃除外）
ACTIVE_STAGES = ("待调研", "调研中", "已联系", "已送样", "仍在跟进")


# ============================================================
# 查竞品结果 -> 追踪看板产品记录 的字段工具
# ============================================================
def _fmt_price(p):
    """'9.9900'/'9.9' -> '9.99'；空返回 ''"""
    if p in (None, ""):
        return ""
    try:
        f = float(p)
    except (ValueError, TypeError):
        return str(p)
    return f"{f:.2f}".rstrip("0").rstrip(".")


def _fmt_thousands(v):
    """数字/字符串 -> 千分位文本；空返回 ''"""
    if v in (None, ""):
        return ""
    try:
        f = float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return str(v)
    return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"


def product_from_lookup(asin, info):
    """查竞品抓取结果 -> 新的追踪看板产品记录（手动添加用）"""
    try:
        sales = int(float(info.get("sales") or 0))
    except (ValueError, TypeError):
        sales = 0
    try:
        monthly = int(float(str(info.get("monthly_sales") or "0").replace(",", "")))
    except (ValueError, TypeError):
        monthly = 0
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "asin": asin,
        "title": info.get("title") or "",
        "brand": info.get("brand") or "",
        "image": info.get("image") or "",
        "price": _fmt_price(info.get("price")),
        "sales": str(sales),
        "monthly_sales": f"{monthly:,}",
        "bsr": _fmt_thousands(info.get("bsr")),
        "rating": info.get("rating") or "",
        "reviews": _fmt_thousands(info.get("reviews")),
        "variants": info.get("variants") or "",
        "available": info.get("available") or "",
        "_progress": "待调研",
        "_source": "manual",
        # 类目：四大类之一；不属于四大类（查竞品未识别/其他）→ 自动填「其他」
        "category": info.get("category") or "其他",
        # 卖家精灵查竞品页面标注（各指标卡 text-muted；'-' 无变化 -> 空字符串）
        "sales_pct": info.get("sales_pct") or "",
        "monthly_pct": info.get("monthly_pct") or "",
        "price_pct": info.get("price_pct") or "",
        "bsr_delta": info.get("bsr_delta") or "",
        "bsr_pct": info.get("bsr_pct") or "",
        "lookup_at": now,
    }


def apply_lookup_to_product(p, info):
    """把查竞品最新值刷到已有产品 p（就地修改），变化标注取自页面各指标卡。

    覆盖字段：title/image/price/sales/monthly_sales/bsr/rating/reviews/available
    标注字段：sales_pct / monthly_pct / price_pct / bsr_delta / bsr_pct / lookup_at
    """
    now = datetime.now().isoformat(timespec="seconds")
    new_price = _fmt_price(info.get("price"))
    p["price"] = new_price or p.get("price", "")
    if info.get("title"):
        p["title"] = info["title"]
    if info.get("image"):
        p["image"] = info["image"]
    if info.get("rating"):
        p["rating"] = info["rating"]
    if info.get("reviews"):
        p["reviews"] = _fmt_thousands(info["reviews"])
    if info.get("bsr"):
        p["bsr"] = _fmt_thousands(info["bsr"])
    if info.get("available"):
        p["available"] = info["available"]
    # 类目/变体：查竞品抓取到的才覆盖（避免把已有手工类目清空）
    if info.get("category"):
        p["category"] = info["category"]
    if info.get("variants"):
        p["variants"] = info["variants"]
    try:
        sales = int(float(info.get("sales") or 0))
        p["sales"] = str(sales)
    except (ValueError, TypeError):
        pass
    try:
        monthly = int(float(str(info.get("monthly_sales") or "0").replace(",", "")))
        p["monthly_sales"] = f"{monthly:,}"
    except (ValueError, TypeError):
        pass
    p["sales_pct"] = info.get("sales_pct") or ""
    p["monthly_pct"] = info.get("monthly_pct") or ""
    p["price_pct"] = info.get("price_pct") or ""
    p["bsr_delta"] = info.get("bsr_delta") or ""
    p["bsr_pct"] = info.get("bsr_pct") or ""
    p["lookup_at"] = now
    return p


class JobManager:
    def __init__(self):
        self._lock = threading.Lock()          # 控制任务启动/状态写入
        self.import_lock = threading.Lock()    # 串行化 dashboard_builder 调用
        self.task_type = "collect"
        self.state = "idle"                    # idle | running | done | error
        self.step = ""
        self.progress = 0
        self.logs = ""
        self.error = ""
        self.result = {}
        self._thread = None

    # ===== 对外 =====
    def is_running(self):
        return self.state == "running"

    def start_collection(self, max_pages=20):
        """启动需求池采集任务；已在运行返回 False"""
        return self.start("collect", max_pages=max_pages)

    def start(self, task_type, **kw):
        """启动任意任务；已在运行返回 False。task_type: collect|lookup_update|lookup_add"""
        if task_type not in ("collect", "lookup_update", "lookup_add"):
            return False
        with self._lock:
            if self.state == "running":
                return False
            self.task_type = task_type
            self.state = "running"
            self.step = "prepare"
            self.progress = 0
            self.logs = ""
            self.error = ""
            self.result = {}
            self._thread = threading.Thread(
                target=self._run, args=(kw,), daemon=True)
            self._thread.start()
            return True

    def snapshot(self):
        """返回状态快照（线程安全读取）"""
        with self._lock:
            return {
                "task_type": self.task_type,
                "state": self.state,
                "step": self.step,
                "progress": self.progress,
                "logs": self.logs[-LOG_LIMIT:],
                "error": self.error,
                "result": self.result,
            }

    # ===== 内部 =====
    def _set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _log(self, text):
        with self._lock:
            self.logs += text + "\n"
            if len(self.logs) > 2 * LOG_LIMIT:
                self.logs = self.logs[-LOG_LIMIT:]

    def _run(self, kw):
        kind = self.task_type
        try:
            if kind == "lookup_update":
                self._run_lookup_update()
            elif kind == "lookup_add":
                self._run_lookup_add(kw.get("asin", ""))
            else:
                self._run_collect(kw.get("max_pages", 20))
        except Exception as e:
            err = "".join(traceback.format_exception_only(type(e), e)).strip()
            self._log(f"[ERROR] {err}")
            self._set(state="error", error=err)

    # ----- 需求池采集 -----
    def _run_collect(self, max_pages):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                # 1) 采集新品池
                self._set(step="collect_new", progress=5)
                self._log("[1/4] 采集新品池 ...")
                collector.run("new", max_pages)
                self._set(progress=20)

                # 2) 采集爆品池
                self._set(step="collect_hot", progress=25)
                self._log("[2/4] 采集爆品池 ...")
                collector.run("hot", max_pages)
                self._set(progress=45)

                # 3) 周环比去重
                self._set(step="diff", progress=50)
                self._log("[3/4] 周环比去重 ...")
                weekly_diff.run_diff()
                self._set(progress=70)

                # 4) 重建需求池看板（在线版 + 离线版）
                self._set(step="build_pool", progress=80)
                self._log("[4/4] 重建需求池看板 ...")
                pool_builder.build_pool_dashboard(
                    output_path=POOL_HTML, web_mode=True)
                try:
                    pool_builder.build_pool_dashboard()  # 离线版 /workspace
                except Exception:
                    pass
                self._set(progress=100, step="done")

            detail = buf.getvalue().strip()
            if detail:
                self._log("---- 采集详细日志(末尾) ----\n" + detail[-2000:])

            result = {}
            for ct in ("new", "hot"):
                pool = pool_builder.load_pool(ct)
                if pool:
                    result[ct] = len(pool.get("products", []))
            self._log("采集完成: 新品 %s 条, 爆品 %s 条"
                      % (result.get("new", 0), result.get("hot", 0)))
            self._set(state="done", result=result)
        finally:
            buf.close()

    # ----- 查竞品批量更新（产品信息更新）-----
    def _run_lookup_update(self):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                import competitor_lookup
                products = db_mod.load_transferred()
                if not products:
                    self._set(state="done", step="done", progress=100)
                    self._log("追踪看板暂无产品")
                    self._set(result={"updated": 0, "failed": 0})
                    return
                targets = [p for p in products
                           if p.get("_progress", "待调研") in ACTIVE_STAGES]
                total = len(targets)
                if not total:
                    self._set(state="done", step="done", progress=100)
                    self._log("没有进行中产品需更新（已合作/放弃不刷新）")
                    self._set(result={"updated": 0, "failed": 0})
                    return
                self._log(f"共 {total} 个进行中产品，开始查竞品更新 …")
                touched = 0
                failed = 0
                for i, p in enumerate(targets):
                    asin = p.get("asin", "")
                    self._set(step="fetch", progress=int(3 + (i + 1) / total * 87))
                    self._log(f"[{i+1}/{total}] 查竞品 {asin} …")
                    info = competitor_lookup.fetch_product(asin)
                    if not info or "error" in info:
                        failed += 1
                        self._log(f"    ⚠ {info.get('error') if info else '无返回'}")
                        continue
                    apply_lookup_to_product(p, info)
                    touched += 1
                if touched:
                    db_mod.save_transferred(products)
                    self._log(f"已更新 {touched} 条数据，正在重建追踪看板 …")
                # 重建看板（即使全部失败也重建，保持页面与服务端一致）
                self._set(step="build", progress=96)
                with self.import_lock:
                    dashboard_builder.build_dashboard(output_path=TRACKING_HTML)
                self._set(state="done", step="done", progress=100,
                          result={"updated": touched, "failed": failed,
                                  "total": total})
                self._log(f"完成：成功 {touched} / 失败 {failed}")
        finally:
            buf.close()

    # ----- 查竞品单 ASIN 添加（手动添加产品）-----
    def _run_lookup_add(self, asin):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                import competitor_lookup
                asin = (asin or "").strip().upper()
                if not asin:
                    self._set(state="error", error="缺少 ASIN")
                    return
                if asin in db_mod.load_canonical_asins():
                    self._set(state="error",
                              error=f"ASIN {asin} 已在追踪看板中，无需重复添加")
                    return
                self._log(f"查竞品抓取 {asin} …")
                self._set(step="fetch", progress=20)
                info = competitor_lookup.fetch_product(asin)
                if not info or "error" in info:
                    msg = info.get("error") if info else "无返回"
                    self._set(state="error", error=f"抓取失败：{msg}")
                    return
                self._set(step="save", progress=60)
                product = product_from_lookup(asin, info)
                db_mod.upsert_transferred(product)
                # 进度默认待调研，与其他产品一致（服务端持久化）
                try:
                    db_mod.save_progress([{"asin": asin, "stage": "待调研",
                                           "note": "", "tracker": "", "order": 0}])
                except Exception:
                    pass
                self._log("已写入商品库，正在重建追踪看板 …")
                self._set(step="build", progress=90)
                with self.import_lock:
                    dashboard_builder.build_dashboard(output_path=TRACKING_HTML)
                title = (product.get("title") or "")[:40]
                self._set(state="done", step="done", progress=100,
                          result={"added": asin, "title": title})
                self._log(f"✅ 已添加 {asin}（{title}）")
        finally:
            buf.close()


# 全局单例
job_manager = JobManager()
