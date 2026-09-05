"""
DuraTech 需求池看板在线版 - Flask 主入口
提供：账号系统 / Cookie 上传+自动采集 / 采集状态轮询 / 需求池数据 / 一键导入追踪看板

生产运行（单进程多线程，保证任务状态共享）:
    waitress-serve --host=127.0.0.1 --port=58901 --threads=8 pool_server:app
"""
import json
import os
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, Response, redirect, send_from_directory, g

WEB_DIR = Path(__file__).parent
SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(WEB_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from db import (init_db, load_latest_pool, load_canonical_asins,
                write_pending_transfer, save_progress, get_all_progress,
                is_locked, record_fail, reset_fail, MAX_FAILS, LOCK_MINUTES,
                load_transferred, save_transferred, upsert_transferred)
from auth import (register, login, logout, get_user_by_token,
                  login_required, admin_required, change_password, TOKEN_TTL_DAYS)
from werkzeug.security import check_password_hash
from tasks import (job_manager, POOL_HTML, TRACKING_HTML,
                   ACTIVE_STAGES, product_from_lookup,
                   apply_lookup_to_product)
from config import SESSIONS_DIR

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))

init_db()

POOL_HTML_TEMPLATE = None  # 惰性生成，见 _get_pool_html


def _get_pool_html():
    """返回 web 版需求池看板 HTML（缺失时生成一次）"""
    if POOL_HTML.exists():
        return POOL_HTML.read_text(encoding="utf-8")
    import pool_builder
    pool_builder.build_pool_dashboard(output_path=POOL_HTML, web_mode=True)
    return POOL_HTML.read_text(encoding="utf-8")


def _get_tracking_html():
    """返回追踪看板 HTML（缺失时生成一次）"""
    if TRACKING_HTML.exists():
        return TRACKING_HTML.read_text(encoding="utf-8")
    import dashboard_builder
    dashboard_builder.build_dashboard(output_path=TRACKING_HTML)
    return TRACKING_HTML.read_text(encoding="utf-8")


def _rebuild_all_html():
    """启动时用最新源码强制重建两个看板 HTML，覆盖旧缓存。

    避免「改了源码/重启服务但页面还是老样子」——旧版本会惰性读取已存在的
    pool.html / board.html 而不重新生成。此处每次进程启动都重建一次，
    保证页面与当前代码一致（请求路径仍读文件，性能不受影响）。
    """
    try:
        import pool_builder
        pool_builder.build_pool_dashboard(output_path=POOL_HTML, web_mode=True)
        print("[startup] 需求池看板 HTML 已用最新源码重建")
    except Exception as e:
        print(f"[startup] 需求池看板 HTML 重建失败: {e}")
    try:
        import dashboard_builder
        dashboard_builder.build_dashboard(output_path=TRACKING_HTML)
        print("[startup] 追踪看板 HTML 已用最新源码重建")
    except Exception as e:
        print(f"[startup] 追踪看板 HTML 重建失败: {e}")


# ============================================================
# 账号系统
# ============================================================
# Cookie 安全下发：HttpOnly + SameSite=Lax 始终开启；Secure 仅在 HTTPS 时开启。
# 当前服务器为 HTTP（无 HTTPS），Secure 必须为 False，否则浏览器拒收 cookie 导致登录失效。
def _secure_cookie_flag():
    # 通过 X-Forwarded-Proto / 请求 scheme 判断是否走 HTTPS
    proto = request.headers.get("X-Forwarded-Proto", "") or request.scheme
    return proto.lower() == "https"


def _set_auth_cookie(resp, token, expires):
    max_age = int((expires - datetime.now()).total_seconds()) if expires else TOKEN_TTL_DAYS * 86400
    resp.set_cookie(
        "duratech_pool_token", token,
        httponly=True,
        samesite="Lax",
        secure=_secure_cookie_flag(),
        max_age=max_age,
        path="/",
    )


@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True, silent=True) or {}
    user, err = register(data.get("username", ""), data.get("password", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    token, expires = None, None
    # 注册后自动登录
    user2, token, expires = login(user["username"], data.get("password", ""))
    resp = jsonify({"ok": True, "token": token, "expires": expires.isoformat() if expires else None,
                    "user": user2})
    _set_auth_cookie(resp, token, expires)
    return resp


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    uname = (data.get("username", "") or "").strip()
    # 暴力破解防护：先查锁定状态（防锁定期内反复尝试）
    if is_locked(uname):
        return jsonify({"ok": False, "error": f"账号已锁定，请 {LOCK_MINUTES} 分钟后再试"}), 423
    user, token, expires = login(uname, data.get("password", ""))
    if not user:
        fails = record_fail(uname)
        remain = max(0, MAX_FAILS - fails)
        msg = "用户名或密码错误"
        if fails >= MAX_FAILS:
            msg = f"失败次数过多，账号已锁定 {LOCK_MINUTES} 分钟"
        elif remain > 0:
            msg = f"用户名或密码错误，还可尝试 {remain} 次"
        return jsonify({"ok": False, "error": msg}), 401
    reset_fail(uname)  # 登录成功清零
    resp = jsonify({"ok": True, "token": token, "expires": expires.isoformat(), "user": user})
    _set_auth_cookie(resp, token, expires)
    return resp


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def api_logout():
    from flask import g
    logout(g.token)
    resp = jsonify({"ok": True})
    resp.delete_cookie("duratech_pool_token", path="/")
    return resp


@app.route("/api/auth/me", methods=["GET"])
@login_required
def api_me():
    from flask import g
    return jsonify({"ok": True, "user": g.user})


@app.route("/api/users", methods=["GET", "POST"])
@admin_required
def api_users():
    from db import get_conn
    if request.method == "GET":
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, username, is_admin, created_at FROM users").fetchall()
        conn.close()
        return jsonify({"ok": True, "users": [dict(r) for r in rows]})
    data = request.get_json(force=True, silent=True) or {}
    user, err = register(data.get("username", ""), data.get("password", ""),
                         is_admin=bool(data.get("is_admin")))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "user": user})


@app.route("/api/users/<int:uid>", methods=["DELETE"])
@admin_required
def api_user_delete(uid):
    from flask import g
    from db import get_conn
    if uid == g.user["id"]:
        return jsonify({"ok": False, "error": "不能删除自己"}), 400
    conn = get_conn()
    admins = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0]
    row = conn.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    if row and row["is_admin"] and admins <= 1:
        conn.close()
        return jsonify({"ok": False, "error": "不能删除最后一个管理员"}), 400
    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/users/<int:uid>/reset-password", methods=["POST"])
@admin_required
def api_user_reset_password(uid):
    """管理员重置任意用户密码（该用户会话同时失效）"""
    from flask import g
    data = request.get_json(force=True, silent=True) or {}
    ok, err = change_password(uid, data.get("password", ""))
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/auth/change-password", methods=["POST"])
@login_required
def api_change_password():
    """用户修改自己的密码（需校验原密码）"""
    from flask import g
    from db import get_conn
    data = request.get_json(force=True, silent=True) or {}
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")
    conn = get_conn()
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
    conn.close()
    if not row or not check_password_hash(row["password_hash"], old_pw):
        return jsonify({"ok": False, "error": "原密码错误"}), 400
    ok, err = change_password(g.user["id"], new_pw)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True})


# ============================================================
# Cookie 上传 + 自动采集
# ============================================================
def _validate_cookies(data):
    """校验 Cookie 结构。接受 EditThisCookie 数组 或 {name:value} 字典。
    返回 (normalized_list, error)"""
    if isinstance(data, dict):
        data = [{"name": k, "value": v, "domain": ""} for k, v in data.items()]
    if not isinstance(data, list) or not data:
        return None, "Cookie 必须是 JSON 数组（EditThisCookie 导出格式）"
    names = set()
    for c in data:
        if not isinstance(c, dict) or "name" not in c or "value" not in c:
            return None, "Cookie 每项必须包含 name 和 value 字段"
        names.add(c["name"])
    if "JSESSIONID" not in names or "Sprite-X-Token" not in names:
        return None, "Cookie 缺少关键字段：JSESSIONID 或 Sprite-X-Token（请导出完整 Cookie）"
    return data, None


@app.route("/api/cookie", methods=["POST"])
@login_required
def api_cookie():
    raw = None
    # 方式1：文件上传
    f = request.files.get("file")
    if f:
        raw = f.read().decode("utf-8", errors="replace")
    # 方式2：文本粘贴
    if raw is None:
        raw = request.form.get("cookie_text") or ""
    if not raw:
        return jsonify({"ok": False, "error": "未收到 Cookie 内容"}), 400

    try:
        data = json.loads(raw)
    except Exception:
        return jsonify({"ok": False, "error": "Cookie 不是合法 JSON"}), 400

    cookies, err = _validate_cookies(data)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    # 备份旧 Cookie（不回显内容）
    sessions_dir = Path(SESSIONS_DIR)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    dest = sessions_dir / "cookies.json"
    if dest.exists():
        bak = sessions_dir / f"cookies_backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
        bak.write_text(dest.read_text(encoding="utf-8"), encoding="utf-8")

    dest.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(dest, 0o600)
    except Exception:
        pass

    # 自动触发任务（task 决定动作；默认 collect 兼容需求池页面上传按钮）
    #   collect        需求池采集（pool.html 上传）
    #   lookup_update  查竞品批量更新产品信息（tracking 页「产品信息更新」）
    #   lookup_add     查竞品抓单 ASIN 后加入追踪看板（tracking 页「添加 ASIN」）
    task = (request.form.get("task") or "collect").strip()
    if task == "lookup_update":
        started = job_manager.start("lookup_update")
        if not started:
            return jsonify({"ok": False, "error": "已有任务在运行，请稍候再试",
                            "running": True}), 409
        return jsonify({"ok": True, "task_type": "lookup_update",
                        "cookies": len(cookies),
                        "message": "Cookie 已保存，开始批量更新产品信息"})
    if task == "lookup_add":
        asin = (request.form.get("asin") or "").strip().upper()
        if not _re.fullmatch(r"[A-Z0-9]{8,12}", asin):
            return jsonify({"ok": False, "error": "ASIN 格式不正确"}), 400
        started = job_manager.start("lookup_add", asin=asin)
        if not started:
            return jsonify({"ok": False, "error": "已有任务在运行，请稍候再试",
                            "running": True}), 409
        return jsonify({"ok": True, "task_type": "lookup_add", "asin": asin,
                        "cookies": len(cookies),
                        "message": "Cookie 已保存，开始获取产品信息"})

    max_pages = request.form.get("max_pages", "20")
    try:
        max_pages = max(1, min(50, int(max_pages)))
    except Exception:
        max_pages = 20
    started = job_manager.start_collection(max_pages)
    if not started:
        return jsonify({"ok": False, "error": "已有采集任务在运行", "running": True}), 409

    return jsonify({"ok": True, "task_type": "collect", "task_started": True,
                    "cookies": len(cookies),
                    "message": f"Cookie 已保存（{len(cookies)} 条），采集已自动开始"})


# ============================================================
# Cookie 有效性检测 / 直接启动追踪任务（不重新上传 Cookie）
# ============================================================
def _check_sellersprite_cookie():
    """检测当前 sessions/cookies.json 是否仍有效（未过期）。

    用卖家精灵 /v2/me 轻量接口：200=有效；302 到登录页=过期。
    """
    try:
        import competitor_lookup as cl
        s = cl._session()
        r = s.get("https://www.sellersprite.com/v2/me",
                  headers=cl.HEADERS, timeout=15, allow_redirects=False)
        return r.status_code == 200 and len(r.text) > 0
    except Exception:
        return False


@app.route("/api/cookie/check", methods=["GET"])
@login_required
def api_cookie_check():
    """检测卖家精灵 Cookie 是否有效。返回 {valid: true/false}"""
    return jsonify({"ok": True, "valid": _check_sellersprite_cookie()})


@app.route("/api/tracking/update/start", methods=["POST"])
@login_required
def api_tracking_update_start():
    """Cookie 有效时直接启动「产品信息更新」异步任务（不上传 Cookie）"""
    started = job_manager.start("lookup_update")
    if not started:
        return jsonify({"ok": False, "error": "已有任务在运行，请稍候再试",
                        "running": True}), 409
    return jsonify({"ok": True, "task_type": "lookup_update",
                    "message": "产品信息更新已开始"})


@app.route("/api/tracking/add/start", methods=["POST"])
@login_required
def api_tracking_add_start():
    """Cookie 有效时直接启动「添加 ASIN」异步任务（不上传 Cookie）"""
    data = request.get_json(force=True, silent=True) or {}
    raw = (data.get("asin") or "").strip()
    asin = raw.upper()
    if not _re.fullmatch(r"[A-Z0-9]{8,12}", asin):
        return jsonify({"ok": False, "error": "ASIN 格式不正确"}), 400
    if asin in load_canonical_asins():
        return jsonify({"ok": False,
                        "error": f"ASIN {asin} 已在追踪看板中，无需重复添加"})
    started = job_manager.start("lookup_add", asin=asin)
    if not started:
        return jsonify({"ok": False, "error": "已有任务在运行，请稍候再试",
                        "running": True}), 409
    return jsonify({"ok": True, "task_type": "lookup_add", "asin": asin,
                    "message": f"已开始添加 {asin}"})


# ============================================================
# 采集状态 / 手动触发
# ============================================================
@app.route("/api/collection/status", methods=["GET"])
@login_required
def api_collection_status():
    # 必须带 ok:True，否则前端 api() 助手会判定为失败并抛错，
    # 导致 renderStatus 永不执行、进度弹窗卡在初始「准备中…/0%」。
    return jsonify({"ok": True, **job_manager.snapshot()})


@app.route("/api/collection/start", methods=["POST"])
@login_required
def api_collection_start():
    data = request.get_json(force=True, silent=True) or {}
    max_pages = int(data.get("max_pages", 20) or 20)
    max_pages = max(1, min(50, max_pages))
    started = job_manager.start_collection(max_pages)
    if not started:
        return jsonify({"ok": False, "error": "已有采集任务在运行", "running": True}), 409
    return jsonify({"ok": True})


# ============================================================
# 需求池数据
# ============================================================
@app.route("/api/pool", methods=["GET"])
@login_required
def api_pool():
    new_pool = load_latest_pool("new")
    hot_pool = load_latest_pool("hot")
    week = (new_pool or hot_pool or {}).get("week", "")

    # 已转入追踪看板的产品自动标记 _imported（前端禁用勾选，实现「转入自动移除」）
    imported = load_canonical_asins()
    for pool_data in (new_pool, hot_pool):
        if not pool_data:
            continue
        for p in pool_data.get("products", []):
            if p.get("asin") in imported:
                p["_imported"] = True

    return jsonify({
        "ok": True,
        "week": week,
        "new": {"stats": (new_pool or {}).get("stats", {}),
                "products": (new_pool or {}).get("products", [])},
        "hot": {"stats": (hot_pool or {}).get("stats", {}),
                "products": (hot_pool or {}).get("products", [])},
    })


# ============================================================
# 一键导入追踪看板
# ============================================================
@app.route("/api/pool/import", methods=["POST"])
@login_required
def api_pool_import():
    data = request.get_json(force=True, silent=True) or {}
    pool = data.get("pool")
    asins = data.get("asins", [])
    if pool not in ("new", "hot"):
        return jsonify({"ok": False, "error": "pool 必须为 new 或 hot"}), 400
    if not isinstance(asins, list) or not asins:
        return jsonify({"ok": False, "error": "请先勾选要导入的产品"}), 400
    asins = [a.strip() for a in asins if a and a.strip()]

    pool_data = load_latest_pool(pool)
    if not pool_data:
        return jsonify({"ok": False, "error": "没有可用的需求池数据，请先采集"}), 400

    by_asin = {p.get("asin", ""): p for p in pool_data.get("products", [])}
    selected = []
    missing = []
    for a in asins:
        if a in by_asin:
            selected.append(by_asin[a])
        else:
            missing.append(a)

    if not selected:
        return jsonify({"ok": False, "error": "所选产品在需求池中不存在", "missing": missing}), 400

    # 确保标签/来源正确
    for p in selected:
        p.setdefault("__label__", "潜力新品" if pool == "new" else "标准爆品")
        p.setdefault("_source", pool)

    existing = load_canonical_asins()
    # 已转入的产品自动移除（不再重复转入）
    selected = [p for p in selected if p.get("asin") not in existing]
    if not selected:
        return jsonify({"ok": True, "selected": 0, "added": 0,
                        "skipped": len(asins),
                        "message": "所选产品均已转入追踪看板，无需重复导入"})

    skipped = sum(1 for p in selected if p.get("asin") in existing)
    added = len(selected) - skipped

    write_pending_transfer(pool, selected)

    # 串行执行看板合并（写 canonical + 重建追踪看板 HTML）
    try:
        with job_manager.import_lock:
            import dashboard_builder
            dashboard_builder.build_dashboard(output_path=TRACKING_HTML)
    except Exception as e:
        return jsonify({"ok": False, "error": f"导入执行失败: {e}"}), 500

    return jsonify({"ok": True, "selected": len(selected),
                    "added": added, "skipped": skipped})


# ============================================================
# 静态资源（登录背景图等）
# ============================================================
STATIC_DIR = WEB_DIR / "static"

@app.route("/static/<path:filename>")
def serve_static(filename):
    """托管 web/static/ 下的静态文件（图片/CSS/JS）"""
    return send_from_directory(str(STATIC_DIR), filename)


# ============================================================
# 全局鉴权拦截（before_request）
# 未登录访问任何非白名单路径，页面跳 /login，API 返回 401。
# 这是需求 1（访问根路径未登录跳登录页）的正规化实现，覆盖所有页面与 API。
# ============================================================
def _is_whitelisted(path):
    """白名单：登录页、静态资源、认证类 API、健康检查——必须匿名可访问"""
    if path in ("/login", "/api/health"):
        return True
    if path.startswith("/static/"):
        return True
    # 认证 API：登录/注册/登出 允许匿名；/api/auth/me 需登录，不放行
    if path.startswith("/api/auth/"):
        return path in ("/api/auth/login", "/api/auth/register", "/api/auth/logout")
    return False


@app.before_request
def _guard():
    p = request.path
    # 登录页自身 / 静态 / 认证 API / 健康检查：直接放行，避免死循环
    if _is_whitelisted(p):
        return None
    user = _current_user()  # 复用 cookie+header 双来源判定
    if user:
        g.user = user
        return None
    # 未登录：API 返回 401，页面跳登录页
    if p.startswith("/api/"):
        return jsonify({"ok": False, "error": "未登录或登录已过期"}), 401
    return redirect("/login")


# ============================================================
# 页面
# ============================================================
LOGIN_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>登录 · DuraTech</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI","Microsoft YaHei",sans-serif;
  background:url('/static/bg-login.jpg') center/contain no-repeat fixed;
  background-color:#11131f;
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  position:relative}
body::before{content:'';position:inset:0;background:rgba(0,0,0,0.25);position:fixed;z-index:0}

.wrap{position:relative;z-index:1;width:100%;max-width:420px;padding:20px}

.card{background:rgba(255,255,255,0.88);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
  border-radius:18px;padding:44px 40px 36px;box-shadow:0 8px 40px rgba(0,0,0,0.18),0 2px 8px rgba(0,0,0,0.08);
  transition:all .35s ease}

/* 标题（放大居中） */
.title{text-align:center;margin-bottom:28px;margin-top:6px}
.title h1{font-size:32px;font-weight:700;color:#1d1d1f;letter-spacing:.5px}
.title p{font-size:13px;color:#86868b;margin-top:6px}

/* 输入框 - Apple 风格 */
.field{position:relative;margin-bottom:16px}
.field input{width:100%;height:46px;padding:0 48px 0 16px;border:1.5px solid #d2d2d7;border-radius:10px;
  font-size:15px;color:#1d1d1f;background:#fff;outline:none;transition:border-color .2s,box-shadow .2s;
  letter-spacing:.2px}
.field input:focus{border-color:#0071e3;box-shadow:0 0 0 4px rgba(0,113,227,.12)}
.field input::placeholder{color:#86868b}
.field .arrow{position:absolute;right:12px;top:50%;transform:translateY(-50%);
  width:28px;height:28px;border-radius:50%;border:none;background:#0071e3;color:#fff;
  cursor:pointer;display:flex;align-items:center;justify-content:center;
  opacity:0;transition:opacity .2s;pointer-events:none}
.field input:focus ~ .arrow,
.field input:not(:placeholder-shown) ~ .arrow{opacity:1;pointer-events:auto}
.field .arrow:hover{background:#0077ed}
.field .arrow svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round}

/* 密码框的箭头始终可见 */
.field.pw-mode .arrow{opacity:1;pointer-events:auto}

/* 错误提示 */
#msg{color:#ff3b30;font-size:13px;min-height:20px;margin-bottom:4px;text-align:center;
  transition:opacity .2s}

/* 记住我 */
.remember{display:flex;align-items:center;justify-content:center;gap:8px;margin:20px 0 16px;
  cursor:pointer;-webkit-tap-highlight-color:transparent}
.remember input[type=checkbox]{appearance:none;-webkit-appearance:none;width:18px;height:18px;
  border:1.5px solid #d2d2d7;border-radius:5px;cursor:pointer;transition:all .15s;
  position:relative;flex-shrink:0}
.remember input:checked{background:#0071e3;border-color:#0071e3}
.remember input:checked::after{content:'✓';position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);color:#fff;font-size:12px;font-weight:700}
.remember span{font-size:13px;color:#1d1d1f;user-select:none}

/* 底部链接 */
.links{text-align:center;margin-top:20px;font-size:13px;line-height:2}
.links a{color:#0071e3;text-decoration:none;transition:color .15s}
.links a:hover{text-decoration:underline}
.links .divider{color:#86868b;margin:0 6px}

/* 注册模式额外字段 */
.extra-field{display:none;animation:fadeIn .25s ease}
.extra-field.show{display:block}

@keyframes fadeIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}

/* 模式切换动画 */
.card.switching{opacity:0;transform:translateY(8px)}

/* 移动端适配 */
@media(max-width:480px){
  .wrap{padding:16px}
  .card{padding:32px 24px 28px;border-radius:14px}
  .title h1{font-size:26px}
  .field input{height:42px;font-size:15px}
}
</style></head><body>
<div class="wrap">
<div class="card" id="card">

  <!-- 标题（放大居中，动态切换） -->
  <div class="title" id="titleArea">
    <h1 id="titleText">登录</h1>
    <p id="titleSub"></p>
  </div>

  <!-- 登录表单 -->
  <form id="loginForm" onsubmit="return false">
    <div id="msg"></div>

    <div class="field">
      <input id="u" type="text" placeholder="用户名" autocomplete="username" autofocus style="padding-right:16px">
    </div>

    <div class="field pw-mode">
      <input id="p" type="password" placeholder="密码" autocomplete="current-password">
      <button type="button" class="arrow" onclick="doLogin()" aria-label="登录">
        <svg viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
      </button>
    </div>

    <!-- 仅注册模式显示：确认密码 -->
    <div class="extra-field" id="confirmField">
      <div class="field pw-mode">
        <input id="p2" type="password" placeholder="确认密码" autocomplete="new-password">
        <button type="button" class="arrow" onclick="doRegister()" aria-label="注册">
          <svg viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </div>

    <!-- 记住我（仅登录模式） -->
    <label class="remember" id="rememberRow">
      <input type="checkbox" id="rememberMe">
      <span>记住我的账户</span>
    </label>
  </form>

  <!-- 底部链接（注册入口已隐藏） -->
  <div class="links" id="linksArea" style="display:none">
    <a href="#" id="toggleLink" onclick="toggleMode()">创建你的账户 →</a>
  </div>

</div><!-- /card -->
</div><!-- /wrap -->

<script>
const TOKEN_KEY = 'duratech_pool_token';
let isRegMode = false;

// 写入登录态 cookie（供服务端 / 与 /tracking 直接鉴权跳转）
function setAuthCookie(token) {
  document.cookie = 'duratech_pool_token=' + token + '; path=/; max-age=' + (30*24*60*60) + '; SameSite=Lax';
}
function clearAuthCookie() {
  document.cookie = 'duratech_pool_token=; path=/; max-age=0; SameSite=Lax';
}

// ---- 模式切换（登录 ↔ 注册）----
function toggleMode() {
  isRegMode = !isRegMode;
  const card = document.getElementById('card');
  card.classList.add('switching');

  setTimeout(() => {
    const t = document.getElementById('titleText');
    const s = document.getElementById('titleSub');
    const cf = document.getElementById('confirmField');
    const tl = document.getElementById('toggleLink');
    const rm = document.getElementById('rememberRow');
    const la = document.getElementById('linksArea');

    if (isRegMode) {
      t.textContent = '创建账户';
      if (s) s.textContent = '';
      cf.classList.add('show');
      tl.textContent = '已有账户？返回登录 →';
      rm.style.display = 'none';
      // 清空输入
      document.getElementById('u').value = '';
      document.getElementById('p').value = '';
      document.getElementById('p2').value = '';
      document.getElementById('u').focus();
    } else {
      t.textContent = '登录';
      if (s) s.textContent = '';
      cf.classList.remove('show');
      tl.textContent = '创建你的账户 →';
      rm.style.display = '';
      document.getElementById('msg').textContent = '';
    }
    card.classList.remove('switching');
  }, 180);
}

// ---- 登录 ----
function doLogin() {
  const u = document.getElementById('u').value.trim();
  const p = document.getElementById('p').value;
  const msg = document.getElementById('msg');
  if (!u || !p) { msg.textContent = '请输入用户名和密码'; return; }

  msg.textContent = ''; msg.style.opacity = '0';
  fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: u, password: p })
  })
  .then(r => r.json())
  .then(d => {
    if (!d.ok) { msg.textContent = d.error || '登录失败'; msg.style.opacity = '1'; return; }
    localStorage.setItem(TOKEN_KEY, d.token);
    setAuthCookie(d.token);
    location.href = '/';
  })
  .catch(e => { msg.textContent = '网络错误，请重试'; msg.style.opacity = '1'; });
}

// ---- 注册 ----
function doRegister() {
  const u = document.getElementById('u').value.trim();
  const p = document.getElementById('p').value;
  const p2 = document.getElementById('p2') ? document.getElementById('p2').value : '';
  const msg = document.getElementById('msg');
  if (!u || !p) { msg.textContent = '请输入用户名和密码'; return; }
  if (p.length < 6) { msg.textContent = '密码至少需要 6 位'; return; }
  if (document.getElementById('confirmField').classList.contains('show') && p !== p2) {
    msg.textContent = '两次输入的密码不一致'; return;
  }

  msg.textContent = ''; msg.style.opacity = '0';
  fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: u, password: p })
  })
  .then(r => r.json())
  .then(d => {
    if (!d.ok) { msg.textContent = d.error || '注册失败'; msg.style.opacity = '1'; return; }
    localStorage.setItem(TOKEN_KEY, d.token);
    setAuthCookie(d.token);
    // 提示首个用户为管理员
    if (d.user && d.user.is_admin) {
      alert('✅ 注册成功！你是本系统的管理员账户。');
    }
    location.href = '/';
  })
  .catch(e => { msg.textContent = '网络错误，请重试'; msg.style.opacity = '1'; });
}

// ---- 回车提交 ----
document.addEventListener('keydown', function(e) {
  if (e.key === 'Enter') {
    if (isRegMode) doRegister(); else doLogin();
  }
});

// ---- 已有 token 则直接跳转 ----
(function() {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) {
    fetch('/api/auth/me', { headers: { 'Authorization': 'Bearer ' + t } })
    .then(r => { if (r.ok) location.href = '/'; })
    .catch(() => {});
  }
})();
</script></body></html>"""


@app.route("/login")
def page_login():
    # 全局 before_request 已保证未登录会跳到此处；已登录则直接进看板
    user = _current_user()
    if user:
        return redirect("/")
    return Response(LOGIN_PAGE, mimetype="text/html")


def _current_user():
    """从 cookie 或 Authorization 头解析当前登录用户，未登录返回 None。
    cookie 由前端登录成功后写入（duratech_pool_token），用于服务端直接鉴权。"""
    token = request.cookies.get("duratech_pool_token") or ""
    if not token:
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not token:
        return None
    return get_user_by_token(token)


@app.route("/")
def index():
    return Response(_get_pool_html(), mimetype="text/html")


@app.route("/tracking")
def tracking():
    return Response(_get_tracking_html(), mimetype="text/html")


@app.route("/api/tracking/edits", methods=["GET"])
@login_required
def api_tracking_edits_get():
    """拉取服务端持久化的追踪看板编辑（进度/备注/排序）"""
    return jsonify({"ok": True, "edits": get_all_progress()})


@app.route("/api/tracking/edits", methods=["POST"])
@login_required
def api_tracking_edits_post():
    """批量保存追踪看板编辑（进度/备注/追踪人/排序）到服务端，实现自动持久化。"""
    data = request.get_json(force=True, silent=True) or {}
    edits = data.get("edits", {})
    updates = []
    for asin, e in edits.items():
        if not asin or not isinstance(e, dict):
            continue
        updates.append({
            "asin": asin,
            "stage": e.get("progress"),
            "note": e.get("subcategory"),
            "tracker": e.get("tracker"),
            "order": e.get("order"),
        })
    n = save_progress(updates)
    return jsonify({"ok": True, "saved": n})


# ============================================================
# 手动添加 ASIN / 查竞品批量更新（任务3 + 任务2）
# 浏览器 UI 走 /api/cookie（task=lookup_update|lookup_add）+ 进度轮询；
# 下方 POST 同步接口保留给后端脚本 / curl 快速调用与回归测试。
# ============================================================
import re as _re


def _tracking_rebuild():
    """串行重建追踪看板 HTML"""
    with job_manager.import_lock:
        import dashboard_builder
        dashboard_builder.build_dashboard(output_path=TRACKING_HTML)


def _product_from_lookup_removed():
    """(移除) 产品构造/更新 helpers 已迁至 tasks.py：
    product_from_lookup / apply_lookup_to_product / _fmt_price / _fmt_thousands"""
    pass


# ---- 产品构造 / 字段更新 helpers 已统一迁移至 tasks.py（product_from_lookup /
#      apply_lookup_to_product / _fmt_price / _fmt_thousands），本文件从 tasks 导入。


# ============================================================
# 市场分析附件（上传 / 列表 / 预览）
# ============================================================
from db import OUTPUT_DIR as _OUTPUT_DIR

ATTACH_DIR = Path(_OUTPUT_DIR) / "attachments"
ATTACH_ALLOWED_EXT = {".html", ".htm", ".xlsx", ".xls"}


@app.route("/api/market/upload", methods=["POST"])
@login_required
def api_market_upload():
    """上传市场分析附件到 output/attachments/{asin}/，支持多文件。"""
    asin = (request.form.get("asin") or "").strip().upper()
    if not _re.fullmatch(r"[A-Z0-9]{8,12}", asin):
        return jsonify({"ok": False, "error": "ASIN 格式不正确"}), 400
    files = request.files.getlist("files") or []
    f = request.files.get("file")
    if f:
        files = [f]
    if not files:
        return jsonify({"ok": False, "error": "未收到文件"}), 400

    dest_dir = ATTACH_DIR / asin
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        name = Path(f.filename or "").name
        ext = Path(name).suffix.lower()
        if ext not in ATTACH_ALLOWED_EXT:
            return jsonify({"ok": False,
                            "error": f"仅支持 HTML/Excel 附件（收到 {ext or '未知'}）"}), 400
        if not name:
            continue
        dest = dest_dir / name
        f.save(str(dest))
        saved.append(name)
    return jsonify({"ok": True, "saved": saved,
                    "message": f"已上传 {len(saved)} 个附件"})


@app.route("/api/market/list", methods=["GET"])
@login_required
def api_market_list():
    """列出某 ASIN 的市场分析附件"""
    asin = (request.args.get("asin") or "").strip().upper()
    if not asin:
        return jsonify({"ok": False, "error": "缺少 ASIN"}), 400
    d = ATTACH_DIR / asin
    files = []
    if d.exists():
        for fp in sorted(d.iterdir()):
            if fp.is_file():
                st = fp.stat()
                files.append({
                    "name": fp.name,
                    "size": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
    return jsonify({"ok": True, "asin": asin, "files": files})


@app.route("/api/market/counts", methods=["GET"])
@login_required
def api_market_counts():
    """批量返回多个 ASIN 的市场分析附件数（供排序/渲染后一次性刷新计数）

    query: asins=B0X,B0Y,...  返回 {counts: {ASIN: n}}
    """
    raw = request.args.get("asins") or ""
    asins = [a.strip().upper() for a in raw.split(",") if a.strip()]
    counts = {}
    for a in asins:
        d = ATTACH_DIR / a
        if d.is_dir():
            counts[a] = sum(1 for fp in d.iterdir() if fp.is_file())
        else:
            counts[a] = 0
    return jsonify({"ok": True, "counts": counts})


@app.route("/api/market/file/<asin>/<path:filename>", methods=["GET"])
@login_required
def api_market_file(asin, filename):
    """预览/下载附件（HTML 新标签打开，Excel 触发浏览器预览/下载）"""
    d = ATTACH_DIR / asin.upper()
    return send_from_directory(str(d), filename)


@app.route("/api/tracking/exists", methods=["GET"])
@login_required
def api_tracking_exists():
    """查询 ASIN 是否已在追踪看板（手动添加前预检）"""
    asin = (request.args.get("asin") or "").strip().upper()
    return jsonify({"ok": True, "asin": asin,
                    "exists": bool(asin) and asin in load_canonical_asins()})


@app.route("/api/tracking/add", methods=["POST"])
@login_required
def api_tracking_add():
    """手动添加 ASIN：查竞品工具抓产品信息 -> 加入追踪看板（待调研）。

    body: {asin}
    返回 {ok, message, product?, reload}；ASIN 已存在返回 ok=False。
    """
    data = request.get_json(force=True, silent=True) or {}
    raw = (data.get("asin") or "").strip()
    asin = raw.upper()
    if not _re.fullmatch(r"[A-Z0-9]{8,12}", asin):
        return jsonify({"ok": False, "error": "ASIN 格式不正确（应为 8-12 位字母数字）"}), 400
    if asin in load_canonical_asins():
        return jsonify({"ok": False,
                        "error": f"ASIN {asin} 已在追踪看板中，无需重复添加"})

    import competitor_lookup
    info = competitor_lookup.fetch_product(asin)
    if "error" in info:
        return jsonify({"ok": False, "error": info["error"]}), 400

    product = product_from_lookup(asin, info)
    product, _is_new = upsert_transferred(product)
    # 进度默认待调研写入 progress 表，与其他产品一致
    try:
        save_progress([{"asin": asin, "stage": "待调研", "note": "",
                        "tracker": "", "order": 0}])
    except Exception:
        pass
    try:
        _tracking_rebuild()
    except Exception as e:
        return jsonify({"ok": False,
                        "error": f"产品已加入，但看板刷新失败: {e}"}), 500

    title = (product.get("title") or "")[:40]
    return jsonify({"ok": True,
                    "message": f"已添加 {asin}（{title}）",
                    "product": product, "reload": True})


@app.route("/api/tracking/refresh", methods=["POST"])
@login_required
def api_tracking_refresh():
    """查竞品批量刷新追踪看板（默认全部进行中产品；也可指定 asins 列表）。

    body: {asins?: [...]}  空/缺省 = 刷新待调研/调研中/已联系/已送样/仍在跟进
    返回 {ok, refreshed: [...], failed: [...], message}
    """
    data = request.get_json(force=True, silent=True) or {}
    given = data.get("asins") or []
    products = load_transferred()
    if not products:
        return jsonify({"ok": False, "error": "追踪看板暂无产品，请先导入或手动添加"}), 400

    if given:
        want = {str(a).strip().upper() for a in given if str(a).strip()}
        targets = [p for p in products if p.get("asin", "").upper() in want]
    else:
        targets = [p for p in products
                   if p.get("_progress", "待调研") in ACTIVE_STAGES]
    if not targets:
        return jsonify({"ok": False, "error": "没有需要刷新的产品（已合作/放弃不刷新）"}), 400

    import competitor_lookup
    asins = [p.get("asin", "") for p in targets if p.get("asin")]
    fresh, errs = competitor_lookup.fetch_products_batch(asins)

    touched = []
    for p in targets:
        info = fresh.get(p.get("asin", "").upper())
        if not info:
            continue
        apply_lookup_to_product(p, info)
        touched.append(p.get("asin"))

    if touched:
        # targets 元素即 products 中对象引用，apply_lookup_to_product 已就地更新，直接整体写回
        save_transferred(products)
        try:
            _tracking_rebuild()
        except Exception as e:
            return jsonify({"ok": False,
                            "error": f"数据已更新，但看板刷新失败: {e}"}), 500

    failed = [e for e in errs]
    msg = (f"✅ 已刷新 {len(touched)} 个产品"
           + (f"，{len(failed)} 个失败" if failed else ""))
    return jsonify({"ok": True, "refreshed": touched,
                    "failed": failed, "message": msg})


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "state": job_manager.snapshot()["state"]})


# 进程启动时强制重建看板 HTML（覆盖旧缓存，确保与当前源码一致）
_rebuild_all_html()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=58901, debug=False, threaded=True)
