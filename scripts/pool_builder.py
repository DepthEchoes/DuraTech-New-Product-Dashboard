"""
DuraTech 需求池看板生成器
一个 HTML 文件，两个 Tab：🆕 新品需求池 | 🔥 爆品需求池
轻量筛选页：浏览、勾选、搜索、导出 Excel、转入追踪看板
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))
from config import CATEGORIES, CATEGORY_SHORT_NAMES, WORKSPACE_OUTPUT, OUTPUT_DIR

WEEKLY_DIR = Path(OUTPUT_DIR) / "weekly"
PENDING_TRANSFER = Path(OUTPUT_DIR) / "pending_transfer.json"

LABEL_COLORS = {
    '潜力新品': '#E2EFDA',
    '标准爆品': '#FCE4D6',
    '头部爆品': '#F4B4B4',
}

# ============================================================
# 在线版（web_mode=True）注入的 UI / JS
# 离线版完全不受影响；这些字符串通过 {header_extra}/{script_extra} 插入模板
# ============================================================
WEB_HEADER_EXTRA = """
<!-- 在线版：登录栏（未登录时显示） -->
<div id="webBar" style="background:#fff;margin:12px 24px 0;border-radius:8px;padding:10px 16px;box-shadow:0 1px 3px rgba(0,0,0,0.1);display:none;align-items:center;gap:8px;flex-wrap:wrap">
  <b style="color:#2F5496">🔐 登录</b>
  <input id="loginUser" placeholder="用户名" style="padding:5px 10px;border:1px solid #ccc;border-radius:4px;font-size:12px">
  <input id="loginPass" type="password" placeholder="密码" style="padding:5px 10px;border:1px solid #ccc;border-radius:4px;font-size:12px">
  <button style="background:#2F5496;color:#fff;padding:6px 14px;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-family:inherit" onclick="doLogin()">登录</button>
  <button style="background:#6c757d;color:#fff;padding:6px 14px;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-family:inherit" onclick="doRegister()">注册</button>
  <span id="loginMsg" style="color:#c00;font-size:12px"></span>
</div>

<!-- 在线版：Cookie 上传弹出组件（默认隐藏，点击右上角按钮触发） -->
<div id="collectCard" style="position:fixed;top:70px;right:24px;width:420px;max-width:calc(100vw - 48px);background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.18);padding:16px;z-index:1000;display:none">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
    <b style="font-size:14px">🍪 卖家精灵 Cookie</b>
    <span id="closeCookieBtn" style="cursor:pointer;font-size:20px;line-height:1;color:#999;padding:2px 6px;border-radius:4px" onclick="toggleCollectCard()" title="关闭">&times;</span>
  </div>
  <div style="font-size:11px;color:#666;margin-bottom:8px">上传后自动开始采集</div>
  <input type="file" id="cookieFile" accept=".json,.txt" style="border:none;font-size:12px;width:100%">
  <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
    <label style="font-size:11px;color:#666;white-space:nowrap">翻页数 <input id="maxPages" type="number" value="20" min="1" max="50" style="width:60px;padding:4px;border:1px solid #ccc;border-radius:4px"></label>
    <button style="background:#28a745;color:#fff;font-weight:bold;padding:7px 14px;border:none;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit" onclick="uploadCookie()">📤 上传并开始采集</button>
  </div>
  <textarea id="cookieText" rows="2" placeholder="或直接粘贴 EditThisCookie 导出的 JSON 文本..." style="width:100%;margin-top:8px;font-size:11px;box-sizing:border-box;padding:6px"></textarea>
  <div id="collectPanel" style="display:none;margin-top:10px">
    <div style="background:#eee;border-radius:4px;height:14px;overflow:hidden">
      <div id="progressBar" style="width:0%;height:100%;background:linear-gradient(90deg,#2F5496,#28a745);transition:width .5s"></div>
    </div>
    <div id="progressLabel" style="font-size:11px;color:#666;margin-top:4px"></div>
    <pre id="collectLog" style="background:#1a1a2e;color:#7ee787;font-size:10px;border-radius:4px;padding:8px;max-height:150px;overflow:auto;white-space:pre-wrap;margin:6px 0 0"></pre>
  </div>
</div>

<!-- 用户管理弹窗（仅管理员可见入口） -->
<div id="userMgmtModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:2000;align-items:center;justify-content:center" onclick="if(event.target===this)closeUserMgmt()">
  <div style="background:#fff;border-radius:12px;width:520px;max-width:94vw;max-height:86vh;overflow:auto;padding:20px 22px;box-shadow:0 12px 48px rgba(0,0,0,.25)">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <b style="font-size:16px;color:#2F5496">⚙ 用户管理</b>
      <span onclick="closeUserMgmt()" style="cursor:pointer;font-size:22px;color:#999;line-height:1">&times;</span>
    </div>
    <div id="userList"></div>
    <div style="margin-top:16px;border-top:1px solid #eee;padding-top:12px">
      <button onclick="showChangeMine()" style="background:#2F5496;color:#fff;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit">🔑 修改我的密码</button>
    </div>
  </div>
</div>

<!-- 右上角用户信息 + Cookie 按钮容器（由 JS 动态注入到 header） -->
<div id="headerRight" style="display:none;align-items:center;gap:10px">
  <button id="cookieBtn" onclick="toggleCollectCard()" title="上传卖家精灵 Cookie" style="background:rgba(255,255,255,.15);color:#fff;border:1px solid rgba(255,255,255,.3);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit;white-space:nowrap">🍪 Cookie</button>
  <button id="userMgmtBtn" onclick="openUserMgmt()" title="用户管理" style="background:rgba(255,255,255,.15);color:#fff;border:1px solid rgba(255,255,255,.3);padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit;white-space:nowrap;display:none">⚙ 用户</button>
  <span id="headerUser" style="font-size:13px;opacity:.9">👤 <b></b></span>
  <button id="logoutBtn" onclick="doLogout()" style="background:rgba(220,53,69,.8);color:#fff;border:none;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit">退出</button>
</div>
"""

WEB_SCRIPT_EXTRA = """
// ============ 在线版：登录态 ============
const TOKEN_KEY = 'duratech_pool_token';
function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setAuthCookie(token) { document.cookie = 'duratech_pool_token=' + token + '; path=/; max-age=' + (30*24*60*60) + '; SameSite=Lax'; }
function clearAuthCookie() { document.cookie = 'duratech_pool_token=; path=/; max-age=0; SameSite=Lax'; }
async function api(url, opts) {
  opts = opts || {};
  opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  const t = getToken();
  if (t) opts.headers['Authorization'] = 'Bearer ' + t;
  const resp = await fetch(url, opts);
  if (resp.status === 401) { showLogin(); throw new Error('未登录，请先登录'); }
  const data = await resp.json().catch(() => ({ ok: false, error: '响应解析失败' }));
  if (!data.ok) throw new Error(data.error || '请求失败');
  return data;
}
function showLogin() {
  const lp = document.getElementById('webBar'); if (lp) lp.style.display = 'flex';
  const hr = document.getElementById('headerRight'); if (hr) hr.style.display = 'none';
}
function showUser(u) {
  // 隐藏登录栏
  const lp = document.getElementById('webBar'); if (lp) lp.style.display = 'none';
  // 把用户信息注入到 header 右侧
  const area = document.getElementById('headerRightArea');
  const hr = document.getElementById('headerRight');
  if (area && hr) {
    hr.style.display = 'flex';
    // 只在首次时移动到 header（避免重复）
    if (!area.contains(hr)) area.appendChild(hr);
    document.querySelector('#headerUser b').textContent = u.username + (u.is_admin ? ' (管理员)' : '');
    const umb = document.getElementById('userMgmtBtn');
    if (umb) umb.style.display = u.is_admin ? 'inline-block' : 'none';
  }
}
async function doLogin() {
  const u = document.getElementById('loginUser').value.trim();
  const p = document.getElementById('loginPass').value;
  const msg = document.getElementById('loginMsg');
  if (!u || !p) { msg.textContent = '请输入用户名和密码'; return; }
  try {
    const d = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: u, password: p }) });
    localStorage.setItem(TOKEN_KEY, d.token); setAuthCookie(d.token); showUser(d.user); msg.textContent = '';
    showToast('✅ 登录成功'); loadPool();
  } catch (e) { msg.textContent = e.message; }
}
async function doRegister() {
  const u = document.getElementById('loginUser').value.trim();
  const p = document.getElementById('loginPass').value;
  const msg = document.getElementById('loginMsg');
  if (!u || !p) { msg.textContent = '请输入用户名和密码'; return; }
  try {
    const d = await api('/api/auth/register', { method: 'POST', body: JSON.stringify({ username: u, password: p }) });
    localStorage.setItem(TOKEN_KEY, d.token); setAuthCookie(d.token); showUser(d.user); msg.textContent = '';
    showToast('✅ 注册成功（首个用户为管理员）'); loadPool();
  } catch (e) { msg.textContent = e.message; }
}
function doLogout() {
  const t = getToken();
  if (t) { fetch('/api/auth/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + t } }).catch(() => {}); }
  localStorage.removeItem(TOKEN_KEY); clearAuthCookie(); showLogin(); showToast('已退出登录');
}

// ============ 在线版：用户管理（管理员） ============
function openUserMgmt() {
  document.getElementById('userMgmtModal').style.display = 'flex';
  loadUsers();
}
function closeUserMgmt() { document.getElementById('userMgmtModal').style.display = 'none'; }
async function loadUsers() {
  try {
    const d = await api('/api/users');
    const box = document.getElementById('userList');
    box.innerHTML = '';
    (d.users || []).forEach(u => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:9px 4px;border-bottom:1px solid #f0f0f0';
      const left = document.createElement('div');
      left.textContent = '👤 ' + u.username + (u.is_admin ? ' (管理员)' : '') + '  #' + u.id;
      const btn = document.createElement('button');
      btn.textContent = '重置密码';
      btn.style.cssText = 'background:#dc3545;color:#fff;border:none;padding:5px 12px;border-radius:5px;cursor:pointer;font-size:12px;font-family:inherit';
      btn.onclick = () => resetUserPassword(u.id, u.username);
      row.appendChild(left); row.appendChild(btn);
      box.appendChild(row);
    });
    if (!d.users || !d.users.length) box.textContent = '（暂无其他用户）';
  } catch (e) { showToast(e.message); }
}
async function resetUserPassword(uid, username) {
  const np = prompt('为「' + username + '」设置新密码（至少 6 位）');
  if (!np) return;
  if (np.length < 6) { showToast('密码至少 6 位'); return; }
  try {
    await api('/api/users/' + uid + '/reset-password', { method: 'POST', body: JSON.stringify({ password: np }) });
    showToast('✅ 已重置 ' + username + ' 的密码');
  } catch (e) { showToast(e.message); }
}
async function showChangeMine() {
  const oldp = prompt('输入当前密码');
  if (!oldp) return;
  const newp = prompt('输入新密码（至少 6 位）');
  if (!newp) return;
  if (newp.length < 6) { showToast('新密码至少 6 位'); return; }
  try {
    await api('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ old_password: oldp, new_password: newp }) });
    showToast('✅ 密码已修改，请重新登录');
    closeUserMgmt();
    doLogout();
  } catch (e) { showToast(e.message); }
}

// ============ 在线版：Cookie 上传 + 采集 ============
async function uploadCookie() {
  const fileInput = document.getElementById('cookieFile');
  const text = document.getElementById('cookieText').value.trim();
  if (!fileInput.files || !fileInput.files[0]) {
    if (!text) { showToast('请选择 Cookie 文件或粘贴 JSON 文本'); return; }
  }
  const fd = new FormData();
  if (fileInput.files && fileInput.files[0]) fd.append('file', fileInput.files[0]);
  else fd.append('cookie_text', text);
  fd.append('max_pages', document.getElementById('maxPages').value || '20');
  const t = getToken();
  try {
    const resp = await fetch('/api/cookie', {
      method: 'POST',
      headers: t ? { 'Authorization': 'Bearer ' + t } : {},
      body: fd
    });
    const d = await resp.json();
    if (resp.status === 401) { showLogin(); return; }
    if (!d.ok) { showToast(d.error || '上传失败'); return; }
    showToast(d.message || 'Cookie 已上传，采集开始');
    document.getElementById('collectPanel').style.display = 'block';
    startPolling();
  } catch (e) { showToast('网络错误: ' + e.message); }
}

// ============ 在线版：采集进度轮询 ============
let pollTimer = null;
function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      const d = await api('/api/collection/status');
      renderStatus(d);
      if (d.state === 'done') {
        stopPolling();
        showToast('✅ 采集完成：新品 ' + ((d.result && d.result.new) || 0) + ' 条 / 爆品 ' + ((d.result && d.result.hot) || 0) + ' 条');
        await loadPool();
      } else if (d.state === 'error') {
        stopPolling();
        showToast('❌ 采集失败：' + d.error);
      }
    } catch (e) { /* 401 已在 api() 处理 */ }
  }, 3000);
  pollNow();
}
async function pollNow() {
  try { const d = await api('/api/collection/status'); renderStatus(d); } catch (e) {}
}
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
function renderStatus(d) {
  const bar = document.getElementById('progressBar');
  const label = document.getElementById('progressLabel');
  const log = document.getElementById('collectLog');
  const stepNames = { prepare: '准备中', collect_new: '采集新品池', collect_hot: '采集爆品池', diff: '周环比去重', build_pool: '重建需求池看板', done: '完成' };
  label.textContent = (stepNames[d.step] || d.step || '') + '  ' + d.progress + '%';
  bar.style.width = (d.progress || 0) + '%';
  if (d.logs) log.textContent = d.logs.slice(-600);
}

// ============ 在线版：一键导入（直接调 API） ============
async function transferToDashboard(pool) {
  const cbs = document.querySelectorAll('#' + pool + 'Body .row-cb:checked');
  if (!cbs.length) { showToast('请先勾选要转入的产品'); return; }
  const asins = [];
  cbs.forEach(cb => asins.push(cb.dataset.asin));
  if (!confirm('确定将 ' + asins.length + ' 个产品一键导入 DuraTech 产品追踪看板吗？')) return;
  try {
    const d = await api('/api/pool/import', {
      method: 'POST',
      body: JSON.stringify({ pool: pool, asins: asins })
    });
    showToast('✅ 已导入 ' + d.selected + ' 条（新增 ' + d.added + ' / 跳过 ' + d.skipped + '）');
    cbs.forEach(cb => { cb.checked = false; cb.disabled = true; cb.parentElement.parentElement.style.opacity = '0.4'; });
    updateCheckCount(pool);
  } catch (e) { showToast(e.message); }
}

// ============ 在线版：数据刷新 ============
async function loadPool() {
  try {
    const d = await api('/api/pool');
    POOLS.new = (d.new && d.new.products) || [];
    POOLS.hot = (d.hot && d.hot.products) || [];
    document.getElementById('newTotal').textContent = POOLS.new.length;
    document.getElementById('hotTotal').textContent = POOLS.hot.length;
    ['new', 'hot'].forEach(p => {
      const cats = new Set(), labels = new Set();
      POOLS[p].forEach(x => { if (x.category) cats.add(x.category.split('&')[0].trim()); if (x.__label__) labels.add(x.__label__); });
      const cs = document.querySelector('.filter-cat[data-pool="' + p + '"]');
      cs.innerHTML = '<option value="all">全部类目</option>';
      cats.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; cs.appendChild(o); });
      const ls = document.querySelector('.filter-label[data-pool="' + p + '"]');
      ls.innerHTML = '<option value="all">全部标签</option>';
      labels.forEach(l => { const o = document.createElement('option'); o.value = l; o.textContent = l; ls.appendChild(o); });
      renderPool(p);
      document.getElementById(p + 'Visible').textContent = POOLS[p].length;
    });
    return d;
  } catch (e) { return null; }
}

// Cookie 弹出组件开关
function toggleCollectCard() {
  const card = document.getElementById('collectCard');
  if (!card) return;
  const isShow = card.style.display !== 'none';
  card.style.display = isShow ? 'none' : 'block';
  if (!isShow) card.classList.add('show'); else card.classList.remove('show');
}
// 点击弹出层外部关闭
document.addEventListener('click', function(e) {
  const card = document.getElementById('collectCard');
  const btn = document.getElementById('cookieBtn');
  if (card && card.style.display !== 'none' && !card.contains(e.target) && btn && !btn.contains(e.target)) {
    card.style.display = 'none'; card.classList.remove('show');
  }
});
// ESC 关闭
document.addEventListener('keydown', function(e) { if (e.key === 'Escape') { const c = document.getElementById('collectCard'); if (c) { c.style.display = 'none'; c.classList.remove('show'); }} });

// 在线版初始化
(async function () {
  // 把 headerRight 移入 header 右侧
  const hr = document.getElementById('headerRight');
  const area = document.getElementById('headerRightArea');
  if (hr && area) area.appendChild(hr);

  showLogin();
  if (getToken()) {
    try { const d = await api('/api/auth/me'); showUser(d.user); } catch (e) {}
    await loadPool();
  }
  pollNow();
})();
"""


def load_pool(collect_type):
    """加载最新的需求池 JSON"""
    pattern = f"{collect_type}_pool_*.json"
    candidates = sorted(WEEKLY_DIR.glob(pattern), reverse=True)
    if not candidates:
        return None
    return json.loads(candidates[0].read_text())


def build_pool_dashboard(output_path=None, web_mode=False):
    """生成需求池看板 HTML
    web_mode=True: 在线版（Cookie 上传 / 采集进度 / 一键导入 API / 登录）"""
    new_pool = load_pool("new")
    hot_pool = load_pool("hot")

    if not new_pool and not hot_pool:
        print("[WARN] 没有需求池数据，请先运行 weekly_diff.py")
        return None

    new_products = new_pool["products"] if new_pool else []
    hot_products = hot_pool["products"] if hot_pool else []
    new_stats = new_pool.get("stats", {}) if new_pool else {}
    hot_stats = hot_pool.get("stats", {}) if hot_pool else {}
    week_label = (new_pool or hot_pool).get("week", datetime.now().strftime("%Y%m%d"))
    date_str = datetime.now().strftime("%Y-%m-%d")

    if output_path is None:
        output_path = Path(WORKSPACE_OUTPUT) / "DuraTech_需求池看板.html"

    new_json = json.dumps(new_products, ensure_ascii=False)
    hot_json = json.dumps(hot_products, ensure_ascii=False)
    label_colors_json = json.dumps(LABEL_COLORS, ensure_ascii=False)

    # 在线版注入额外 UI / JS
    header_extra = WEB_HEADER_EXTRA if web_mode else ""
    script_extra = WEB_SCRIPT_EXTRA if web_mode else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DuraTech 需求池看板 {week_label}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "Microsoft YaHei", "微软雅黑", Arial, sans-serif; font-size: 13px; background: #f0f2f5; }}
.header {{ background: linear-gradient(135deg, #1a3a5c, #2F5496); color: #fff; padding: 16px 24px; display: flex; align-items: flex-start; justify-content: space-between; }}
.header .header-left {{ flex: 1; min-width: 0; }}
.header h1 {{ font-size: 20px; margin-bottom: 4px; }}
.header .sub {{ font-size: 12px; opacity: 0.8; }}
.header .nav-link {{ color: rgba(255,255,255,.8); text-decoration: none; font-size: 13px; margin-left: 16px; transition: color .15s; white-space: nowrap; }}
.header .nav-link:hover {{ color: #fff; }}
/* 看板切换导航（需求池 / 产品追踪） */
.topnav {{ display: flex; gap: 10px; padding: 0 24px; background: linear-gradient(135deg, #16314f, #24447e); }}
.nav-tab {{ display: inline-flex; align-items: center; gap: 6px; padding: 11px 22px; color: rgba(255,255,255,.7); text-decoration: none; font-size: 14px; font-weight: 600; border-bottom: 3px solid transparent; transition: all .15s; white-space: nowrap; }}
.nav-tab:hover {{ color: #fff; text-decoration: none; }}
.nav-tab.active {{ color: #fff; background: rgba(255,255,255,.10); border-bottom-color: #4da3ff; }}
/* Tab 切换 */
.tabs {{ display: flex; margin: 16px 24px 0; gap: 0; }}
.tab-btn {{ padding: 10px 28px; border: none; background: #e9ecef; cursor: pointer; font-size: 14px; font-family: inherit; border-radius: 8px 8px 0 0; font-weight: bold; color: #666; }}
.tab-btn.active {{ background: #fff; color: #2F5496; box-shadow: 0 -2px 6px rgba(0,0,0,0.08); }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
/* 统计行 */
.stats-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; padding: 12px 24px; background: #fff; }}
.stat-card {{ background: #f8f9fa; border-radius: 8px; padding: 12px; text-align: center; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s; border: 2px solid transparent; user-select: none; }}
.stat-card:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
.stat-card.active {{ border-color: #2F5496; background: #eef2f9; }}
.stat-card .num {{ font-size: 24px; font-weight: bold; color: #2F5496; }}
.stat-card .label {{ font-size: 11px; color: #888; margin-top: 4px; }}
/* 工具栏 */
.toolbar {{ background: #fff; margin: 0 24px; border-top: 1px solid #eee; padding: 10px 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
.toolbar select, .toolbar input {{ padding: 5px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; font-family: inherit; }}
.toolbar button {{ padding: 6px 14px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-family: inherit; }}
.btn-transfer {{ background: #28a745; color: #fff; font-weight: bold; }}
.btn-transfer:hover {{ background: #1e7e34; }}
.btn-export {{ background: #2F5496; color: #fff; }}
.btn-export:hover {{ background: #1e3a6e; }}
.btn-select {{ background: #6c757d; color: #fff; }}
.toolbar .count {{ margin-left: auto; font-weight: bold; color: #2F5496; }}
/* 表格 */
.table-wrap {{ margin: 0 24px 24px; background: #fff; border-radius: 0 0 8px 8px; overflow: visible; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #2F5496; color: #fff; padding: 8px 6px; font-size: 11px; text-align: center; white-space: nowrap; position: sticky; top: 0; z-index: 10; }}
td {{ padding: 10px 6px; border-bottom: 1px solid #eee; font-size: 11px; vertical-align: middle; }}
tr:hover {{ background: #f8f9ff; }}
img.product-img {{ width: 100px; height: 100px; object-fit: contain; border: 1px solid #eee; border-radius: 4px; background: #fafafa; }}
.label-badge {{ display: inline-block; padding: 2px 7px; border-radius: 3px; font-size: 10px; font-weight: bold; }}
.title-cell {{ max-width: 260px; word-wrap: break-word; }}
.num-cell {{ text-align: right; white-space: nowrap; }}
.price-cell {{ color: #c00; font-weight: bold; }}
.rating {{ color: #f0ad4e; font-weight: bold; }}
a {{ color: #2F5496; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.growth-note {{ font-size: 10px; color: #198754; white-space: nowrap; }}
.growth-note.new {{ color: #0d6efd; }}
.toast {{ position: fixed; top: 20px; right: 20px; background: #28a745; color: #fff; padding: 10px 20px; border-radius: 4px; z-index: 9999; display: none; font-size: 13px; }}
@media (max-width: 1200px) {{ .stats-row {{ grid-template-columns: repeat(3, 1fr); }} }}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>📋 DuraTech 需求池看板</h1>
    <div class="sub">周次: {week_label} · 生成于 {date_str} · 勾选产品后可转入追踪看板</div>
  </div>
  <div id="headerRightArea"></div>
</div>

<div class="topnav">
  <a href="/" class="nav-tab active">📋 需求池看板</a>
  <a href="/tracking" class="nav-tab">📊 产品追踪看板 →</a>
</div>

{header_extra}

<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('new')">🆕 新品需求池 <span id="newCount">{len(new_products)}</span></button>
  <button class="tab-btn" onclick="switchTab('hot')">🔥 爆品需求池 <span id="hotCount">{len(hot_products)}</span></button>
</div>

<!-- 新品池 -->
<div class="tab-content active" id="tab-new">
<div class="stats-row">
  <div class="stat-card" onclick="filterByGrowth('new', null)"><div class="num" id="newTotal">{len(new_products)}</div><div class="label">产品总数</div></div>
  <div class="stat-card" id="newCardNew" onclick="filterByGrowth('new', 'new')"><div class="num" id="newNew">{new_stats.get('new', 0)}</div><div class="label">🆕 新上架</div></div>
  <div class="stat-card" id="newCardGrew" onclick="filterByGrowth('new', 'grew')"><div class="num" id="newGrew" style="color:#198754">{new_stats.get('grew', 0)}</div><div class="label">📈 销量增长</div></div>
  <div class="stat-card" id="newCardSelected"><div class="num" id="newSelected" style="color:#2F5496">0</div><div class="label">已勾选</div></div>
</div>
<div class="toolbar">
  <label>类目:</label>
  <select class="filter-cat" data-pool="new" onchange="applyFilters('new')">
    <option value="all">全部类目</option>
  </select>
  <label>标签:</label>
  <select class="filter-label" data-pool="new" onchange="applyFilters('new')">
    <option value="all">全部标签</option>
  </select>
  <label>搜索:</label>
  <input type="text" class="filter-search" data-pool="new" placeholder="ASIN/品牌/标题..." oninput="applyFilters('new')">
  <button class="btn-select" onclick="toggleAll('new')">☑ 全选/反选</button>
  <button class="btn-export" onclick="exportSelectedCSV('new')">📥 导出勾选 Excel</button>
  <button class="btn-transfer" onclick="transferToDashboard('new')">📤 转入追踪看板</button>
  <span class="count">显示: <span id="newVisible">{len(new_products)}</span>/{len(new_products)}</span>
</div>
<div class="table-wrap">
<table><thead><tr>
  <th style="width:28px"><input type="checkbox" class="check-all" data-pool="new" onchange="toggleAll('new')" title="全选"></th>
  <th style="width:110px">主图</th><th>类目</th><th>ASIN</th><th style="width:70px">品牌</th><th>标题</th><th>标签</th>
  <th>近30天销量</th><th>月销售额</th><th>售价</th><th>上架时间</th>
  <th>评分</th><th>评论</th><th>BSR</th><th>变体</th><th>📝 备注</th>
</tr></thead>
<tbody id="newBody"></tbody></table>
</div>
</div>

<!-- 爆品池 -->
<div class="tab-content" id="tab-hot">
<div class="stats-row">
  <div class="stat-card" onclick="filterByGrowth('hot', null)"><div class="num" id="hotTotal">{len(hot_products)}</div><div class="label">产品总数</div></div>
  <div class="stat-card" id="hotCardNew" onclick="filterByGrowth('hot', 'new')"><div class="num" id="hotNew">{hot_stats.get('new', 0)}</div><div class="label">🆕 新上架</div></div>
  <div class="stat-card" id="hotCardGrew" onclick="filterByGrowth('hot', 'grew')"><div class="num" id="hotGrew" style="color:#198754">{hot_stats.get('grew', 0)}</div><div class="label">📈 销量增长</div></div>
  <div class="stat-card"><div class="num" id="hotSelected" style="color:#2F5496">0</div><div class="label">已勾选</div></div>
</div>
<div class="toolbar">
  <label>类目:</label>
  <select class="filter-cat" data-pool="hot" onchange="applyFilters('hot')">
    <option value="all">全部类目</option>
  </select>
  <label>标签:</label>
  <select class="filter-label" data-pool="hot" onchange="applyFilters('hot')">
    <option value="all">全部标签</option>
  </select>
  <label>搜索:</label>
  <input type="text" class="filter-search" data-pool="hot" placeholder="ASIN/品牌/标题..." oninput="applyFilters('hot')">
  <button class="btn-select" onclick="toggleAll('hot')">☑ 全选/反选</button>
  <button class="btn-export" onclick="exportSelectedCSV('hot')">📥 导出勾选 Excel</button>
  <button class="btn-transfer" onclick="transferToDashboard('hot')">📤 转入追踪看板</button>
  <span class="count">显示: <span id="hotVisible">{len(hot_products)}</span>/{len(hot_products)}</span>
</div>
<div class="table-wrap">
<table><thead><tr>
  <th style="width:28px"><input type="checkbox" class="check-all" data-pool="hot" onchange="toggleAll('hot')" title="全选"></th>
  <th style="width:110px">主图</th><th>类目</th><th>ASIN</th><th style="width:70px">品牌</th><th>标题</th><th>标签</th>
  <th>近30天销量</th><th>月销售额</th><th>售价</th><th>上架时间</th>
  <th>评分</th><th>评论</th><th>BSR</th><th>变体</th><th>📝 备注</th>
</tr></thead>
<tbody id="hotBody"></tbody></table>
</div>
</div>

<div class="toast" id="toast"></div>

<script>
const POOLS = {{
  new: {new_json},
  hot: {hot_json}
}};
const LABEL_COLORS = {label_colors_json};

// ===== Tab 切换 =====
function switchTab(tab) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelector(`.tab-btn:${{tab === 'new' ? 'first' : 'last'}}-child`).classList.add('active');
  document.getElementById('tab-' + tab).classList.add('active');
}}

// ===== 渲染表格 =====
function createRow(p, pool) {{
  const tr = document.createElement('tr');
  const img = p.image ? `<img class="product-img" src="${{p.image}}" loading="lazy" onerror="this.style.display='none'">` : '';
  const catShort = (p.category || '').split('&')[0].trim();
  const labelBg = LABEL_COLORS[p.__label__] || '#e9ecef';
  const sourceLabel = p._source === 'new' ? '🆕新品' : (p._source === 'hot' ? '🔥爆品' : '');
  const growthClass = (p._growth_note || '').startsWith('🆕') ? 'new' : '';
  
  tr.innerHTML = `
    <td style="text-align:center"><input type="checkbox" class="row-cb" data-asin="${{p.asin}}" data-pool="${{pool}}" onchange="updateCheckCount('${{pool}}')"></td>
    <td>${{img}}</td>
    <td>${{catShort}}</td>
    <td><a href="https://www.amazon.com/dp/${{p.asin}}" target="_blank">${{p.asin}}</a></td>
    <td>${{p.brand || ''}}</td>
    <td class="title-cell" title="${{(p.title || '').replace(/"/g, '&quot;')}}">${{p.title || ''}}</td>
    <td><span class="label-badge" style="background:${{labelBg}}">${{p.__label__ || ''}}</span></td>
    <td class="num-cell">${{p.sales || ''}}</td>
    <td class="num-cell">${{p.monthly_sales || ''}}</td>
    <td class="num-cell price-cell">${{p.price || ''}}</td>
    <td>${{p.available || ''}}</td>
    <td class="num-cell rating">${{p.rating || ''}}</td>
    <td class="num-cell">${{p.reviews || ''}}</td>
    <td class="num-cell">${{p.bsr || ''}}</td>
    <td class="num-cell">${{p.variants || ''}}</td>
    <td><span class="growth-note ${{growthClass}}">${{p._growth_note || ''}}</span></td>`;
  return tr;
}}

function renderPool(pool) {{
  const tbody = document.getElementById(pool + 'Body');
  tbody.innerHTML = '';
  POOLS[pool].forEach(p => tbody.appendChild(createRow(p, pool)));
}}

// ===== 筛选 =====
// 当前激活的备注筛选状态: {{ pool: 'new'|'grew'|null }}
const growthFilter = {{}};

function applyFilters(pool) {{
  const fc = document.querySelector(`.filter-cat[data-pool="${{pool}}"]`).value;
  const fl = document.querySelector(`.filter-label[data-pool="${{pool}}"]`).value;
  const fs = document.querySelector(`.filter-search[data-pool="${{pool}}"]`).value.toLowerCase();
  const gf = growthFilter[pool] || null;
  
  const tbody = document.getElementById(pool + 'Body');
  const rows = tbody.querySelectorAll('tr');
  let visible = 0;
  
  rows.forEach(row => {{
    const cat = (row.cells[2]?.textContent || '').trim();
    const label = (row.querySelector('.label-badge')?.textContent || '').trim();
    const asin = (row.querySelector('a')?.textContent || '').toLowerCase();
    const brand = (row.cells[4]?.textContent || '').toLowerCase();
    const title = (row.querySelector('.title-cell')?.textContent || '').toLowerCase();
    const growthNote = (row.querySelector('.growth-note')?.textContent || '').trim();
    
    let show = true;
    if (fc !== 'all' && !cat.startsWith(fc.split('&')[0].trim())) show = false;
    if (fl !== 'all' && label !== fl) show = false;
    if (fs && !(asin.includes(fs) || brand.includes(fs) || title.includes(fs))) show = false;
    if (gf === 'new' && !growthNote.startsWith('🆕')) show = false;
    if (gf === 'grew' && !growthNote.startsWith('📈')) show = false;
    
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  
  document.getElementById(pool + 'Visible').textContent = visible;
}}

// ===== 点击卡片按备注筛选 =====
function filterByGrowth(pool, type) {{
  // null = 清除筛选，点击产品总数时使用
  if (type === null) {{
    growthFilter[pool] = null;
    document.getElementById(pool + 'CardNew').classList.remove('active');
    document.getElementById(pool + 'CardGrew').classList.remove('active');
    applyFilters(pool);
    return;
  }}
  // 如果已激活则取消筛选
  if (growthFilter[pool] === type) {{
    growthFilter[pool] = null;
    document.getElementById(pool + 'CardNew').classList.remove('active');
    document.getElementById(pool + 'CardGrew').classList.remove('active');
  }} else {{
    growthFilter[pool] = type;
    // 高亮对应卡片
    document.getElementById(pool + 'CardNew').classList.toggle('active', type === 'new');
    document.getElementById(pool + 'CardGrew').classList.toggle('active', type === 'grew');
  }}
  applyFilters(pool);
}}

// ===== 全选/反选 =====
function toggleAll(pool) {{
  const checkAll = document.querySelector(`.check-all[data-pool="${{pool}}"]`);
  const rows = document.querySelectorAll(`#${{pool}}Body tr`);
  let anyChecked = false;
  rows.forEach(row => {{ if (row.style.display !== 'none' && row.querySelector('.row-cb').checked) anyChecked = true; }});
  
  // 如果所有可见的都勾选了，则反选；否则全选
  const targetState = !anyChecked;
  rows.forEach(row => {{
    if (row.style.display !== 'none') row.querySelector('.row-cb').checked = targetState;
  }});
  checkAll.checked = targetState;
  updateCheckCount(pool);
}}

function updateCheckCount(pool) {{
  const cbs = document.querySelectorAll(`#${{pool}}Body .row-cb:checked`);
  document.getElementById(pool + 'Selected').textContent = cbs.length;
}}

// ===== 导出勾选 CSV =====
function exportSelectedCSV(pool) {{
  const cbs = document.querySelectorAll(`#${{pool}}Body .row-cb:checked`);
  if (cbs.length === 0) {{ showToast('请先勾选产品'); return; }}
  
  const headers = ['类目','ASIN','品牌','标题','标签','来源','近30天销量','月销售额','售价','上架时间','评分','评论数','BSR','变体数','主图链接','备注'];
  const selected = [];
  cbs.forEach(cb => {{
    const p = POOLS[pool].find(x => x.asin === cb.dataset.asin);
    if (p) selected.push([p.category||'', p.asin, p.brand||'', p.title||'', p.__label__||'',
      p._source||'', p.sales||'', p.monthly_sales||'', p.price||'', p.available||'',
      p.rating||'', p.reviews||'', p.bsr||'', p.variants||'', p.image||'', p._growth_note||'']);
  }});
  
  let csv = '\\uFEFF' + headers.join(',') + '\\n';
  selected.forEach(r => csv += r.map(v => '"' + (v||'').replace(/"/g, '""') + '"').join(',') + '\\n');
  
  const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'DuraTech_' + (pool === 'new' ? '新品' : '爆品') + '_勾选_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click(); URL.revokeObjectURL(url);
  showToast('已导出 ' + selected.length + ' 条');
}}

// ===== 转入追踪看板 =====
function transferToDashboard(pool) {{
  const cbs = document.querySelectorAll(`#${{pool}}Body .row-cb:checked`);
  if (cbs.length === 0) {{ showToast('请先勾选要转入的产品'); return; }}
  if (!confirm('确定将 ' + cbs.length + ' 个产品转入 DuraTech 产品追踪看板吗？')) return;
  
  const selected = [];
  cbs.forEach(cb => {{
    const p = POOLS[pool].find(x => x.asin === cb.dataset.asin);
    if (p) {{
      // 确保标签和来源字段正确
      p.__label__ = p.__label__ || (pool === 'new' ? '潜力新品' : '标准爆品');
      p._source = p._source || (pool === 'new' ? 'new' : 'hot');
      selected.push(p);
    }}
  }});
  
  // 写入 pending_transfer.json（浏览器无法直接写文件，改为下载 JSON 让用户/AI 处理）
  // 实际上：浏览器用 Blob 下载 JSON，用户把这个文件放到指定目录
  const json = JSON.stringify({{ pool: pool, products: selected, transfer_time: new Date().toISOString() }}, null, 2);
  const blob = new Blob([json], {{ type: 'application/json;charset=utf-8' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'pending_transfer_' + new Date().toISOString().slice(0,10) + '.json';
  a.click();
  URL.revokeObjectURL(url);
  
  showToast('已导出 ' + selected.length + ' 条转入文件！请将下载的 JSON 发给我，我会自动更新追踪看板');
  
  // 视觉反馈：已转出的行变灰
  cbs.forEach(cb => {{ cb.parentElement.parentElement.style.opacity = '0.4'; cb.disabled = true; }});
}}

// ===== 工具 =====
function showToast(msg) {{
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}}

// ===== 初始化 =====
// 填充类目和标签筛选选项
['new', 'hot'].forEach(pool => {{
  const cats = new Set();
  const labels = new Set();
  POOLS[pool].forEach(p => {{
    if (p.category) cats.add(p.category.split('&')[0].trim());
    if (p.__label__) labels.add(p.__label__);
  }});
  
  const catSelect = document.querySelector(`.filter-cat[data-pool="${{pool}}"]`);
  cats.forEach(c => {{ const opt = document.createElement('option'); opt.value = c; opt.textContent = c; catSelect.appendChild(opt); }});
  
  const labelSelect = document.querySelector(`.filter-label[data-pool="${{pool}}"]`);
  labels.forEach(l => {{ const opt = document.createElement('option'); opt.value = l; opt.textContent = l; labelSelect.appendChild(opt); }});
  
  renderPool(pool);
}});
{script_extra}
</script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding='utf-8')
    print(f"[OK] 需求池看板已生成: {output_path}")
    print(f"     新品池: {len(new_products)} 条, 爆品池: {len(hot_products)} 条")
    return output_path


if __name__ == "__main__":
    build_pool_dashboard()
