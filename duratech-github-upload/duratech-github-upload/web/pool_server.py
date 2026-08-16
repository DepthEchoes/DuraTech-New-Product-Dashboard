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
from pathlib import Path

from flask import Flask, request, jsonify, Response, redirect, send_from_directory

WEB_DIR = Path(__file__).parent
SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(WEB_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from db import (init_db, load_latest_pool, load_canonical_asins,
                write_pending_transfer)
from auth import (register, login, logout, get_user_by_token,
                  login_required, admin_required)
from tasks import job_manager, POOL_HTML, TRACKING_HTML
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
@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True, silent=True) or {}
    user, err = register(data.get("username", ""), data.get("password", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    token, expires = None, None
    # 注册后自动登录
    user2, token, expires = login(user["username"], data.get("password", ""))
    return jsonify({"ok": True, "token": token, "expires": expires.isoformat() if expires else None,
                    "user": user2})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    user, token, expires = login(data.get("username", ""), data.get("password", ""))
    if not user:
        return jsonify({"ok": False, "error": "用户名或密码错误"}), 401
    return jsonify({"ok": True, "token": token, "expires": expires.isoformat(), "user": user})


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def api_logout():
    from flask import g
    logout(g.token)
    return jsonify({"ok": True})


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

    # 自动触发采集
    max_pages = request.form.get("max_pages", "20")
    try:
        max_pages = max(1, min(50, int(max_pages)))
    except Exception:
        max_pages = 20
    started = job_manager.start_collection(max_pages)
    if not started:
        return jsonify({"ok": False, "error": "已有采集任务在运行", "running": True}), 409

    return jsonify({"ok": True, "task_started": True,
                    "cookies": len(cookies),
                    "message": f"Cookie 已保存（{len(cookies)} 条），采集已自动开始"})


# ============================================================
# 采集状态 / 手动触发
# ============================================================
@app.route("/api/collection/status", methods=["GET"])
@login_required
def api_collection_status():
    return jsonify(job_manager.snapshot())


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
    return jsonify({
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
# 页面
# ============================================================
LOGIN_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>登录 · DuraTech</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI","Microsoft YaHei",sans-serif;
  background:url('/static/bg-login.jpg') center/cover no-repeat fixed;
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  position:relative}
body::before{content:'';position:inset:0;background:rgba(0,0,0,0.25);position:fixed;z-index:0}

.wrap{position:relative;z-index:1;width:100%;max-width:420px;padding:20px}

.card{background:rgba(255,255,255,0.88);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
  border-radius:18px;padding:44px 40px 36px;box-shadow:0 8px 40px rgba(0,0,0,0.18),0 2px 8px rgba(0,0,0,0.08);
  transition:all .35s ease}

/* 标题 */
.title{text-align:center;margin-bottom:32px}
.title h1{font-size:22px;font-weight:600;color:#1d1d1f;letter-spacing:.3px}
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

/* DuraTech Logo 区域 */
.brand{text-align:center;margin-bottom:28px}
.brand-logo{display:inline-flex;align-items:center;gap:10px}
.brand-icon{width:36px;height:36px;border-radius:9px;background:linear-gradient(135deg,#00a8cc,#0071e3);
  display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:16px;
  box-shadow:0 2px 8px rgba(0,113,227,.3)}
.brand-name{font-size:20px;font-weight:700;color:#1d1d1f;letter-spacing:.5px}
.brand-name span{color:#0071e3}
.brand-tagline{font-size:11px;color:#86868b;margin-top:4px;letter-spacing:1.5px;text-transform:uppercase}

/* 移动端适配 */
@media(max-width:480px){
  .wrap{padding:16px}
  .card{padding:32px 24px 28px;border-radius:14px}
  .title h1{font-size:19px}
  .field input{height:42px;font-size:15px}
}
</style></head><body>
<div class="wrap">
<div class="card" id="card">

  <!-- 品牌 -->
  <div class="brand">
    <div class="brand-logo"><div style="font-family:Arial">D</div></div>
    <div>
      <div class="brand-name">Dura<span>Tech</span></div>
      <div class="brand-tagline">Built to Last</div>
    </div>
  </div>

  <!-- 标题（动态切换） -->
  <div class="title" id="titleArea">
    <h1 id="titleText">登录</h1>
    <p id="titleSub">登录后使用需求池看板与产品追踪系统</p>
  </div>

  <!-- 登录表单 -->
  <form id="loginForm" onsubmit="return false">
    <div id="msg"></div>

    <div class="field">
      <input id="u" type="text" placeholder="用户名" autocomplete="username" autofocus>
      <button type="button" class="arrow" onclick="doLogin()" aria-label="继续">
        <svg viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
      </button>
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

  <!-- 底部链接 -->
  <div class="links" id="linksArea">
    <a href="#" id="toggleLink" onclick="toggleMode()">创建你的账户 →</a>
  </div>

</div><!-- /card -->
</div><!-- /wrap -->

<script>
const TOKEN_KEY = 'duratech_pool_token';
let isRegMode = false;

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
      s.textContent = '注册后即可使用 DuraTech 看板系统';
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
      s.textContent = '登录后使用需求池看板与产品追踪系统';
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
    return Response(LOGIN_PAGE, mimetype="text/html")


@app.route("/")
def index():
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not token:
        # 页面 HTML 无需服务端鉴权（前端自行判断 401 跳登录），直接返回
        pass
    return Response(_get_pool_html(), mimetype="text/html")


@app.route("/tracking")
def tracking():
    return Response(_get_tracking_html(), mimetype="text/html")


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "state": job_manager.snapshot()["state"]})


# 进程启动时强制重建看板 HTML（覆盖旧缓存，确保与当前源码一致）
_rebuild_all_html()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=58901, debug=False, threaded=True)
