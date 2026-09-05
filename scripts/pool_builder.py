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
from config import CATEGORIES, CATEGORY_SHORT_NAMES, WORKSPACE_OUTPUT, OUTPUT_DIR, SUB_CATEGORIES

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
  <div id="collectPanel" style="display:none;margin-top:12px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <span id="progressStep" style="font-size:12px;font-weight:bold;color:#2F5496">准备中…</span>
      <span id="progressPct" style="font-size:14px;font-weight:bold;color:#2F5496">0%</span>
    </div>
    <div style="background:#e9ecef;border-radius:8px;height:22px;overflow:hidden;position:relative">
      <div id="progressBar" style="width:0%;height:100%;background:linear-gradient(90deg,#2F5496,#28a745);transition:width .5s;border-radius:8px"></div>
    </div>
    <div id="progressLabel" style="font-size:11px;color:#666;margin-top:6px"></div>
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
<div id="headerRight" style="display:none;align-items:center;gap:8px">
  <button id="cookieBtn" class="hb-btn outline" onclick="toggleCollectCard()" title="上传卖家精灵 Cookie">🍪 Cookie</button>
  <button id="userMgmtBtn" class="hb-btn outline" onclick="openUserMgmt()" title="用户管理" style="display:none">⚙ 用户</button>
  <span id="headerUser" class="hb-user">👤 <b></b></span>
  <button id="logoutBtn" class="hb-btn danger" onclick="doLogout()">退出</button>
</div>
"""

WEB_SCRIPT_EXTRA = """
// ============ 安全工具 ============
// 转义 HTML 特殊字符，防止产品字段（标题/品牌/备注/类目等用户可控内容）造成 XSS
function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
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
  showToast('上传中，请稍候…');
  try {
    const resp = await fetch('/api/cookie', {
      method: 'POST',
      headers: t ? { 'Authorization': 'Bearer ' + t } : {},
      body: fd
    });
    const d = await resp.json();
    if (resp.status === 401) { showToast('登录已过期，请重新登录'); showLogin(); return; }
    if (!d.ok) { showToast(d.error || '上传失败'); return; }
    showToast(d.message || 'Cookie 已上传，采集开始');
    document.getElementById('collectPanel').style.display = 'block';
    startPolling();
  } catch (e) { showToast('网络错误: ' + e.message); }
}

// ============ 在线版：采集进度轮询 ============
// 状态轮询独立请求：不依赖通用 api() 的 ok 判定，避免状态接口偶发缺 ok 时
// renderStatus 永不执行、进度弹窗假死在「准备中…/0%」。
let pollTimer = null;
async function fetchStatus() {
  const t = getToken();
  const headers = {};
  if (t) headers['Authorization'] = 'Bearer ' + t;
  const resp = await fetch('/api/collection/status', { headers });
  if (resp.status === 401) { showLogin(); throw new Error('未登录'); }
  return await resp.json().catch(() => ({}));
}
function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      const d = await fetchStatus();
      renderStatus(d);
      if (d.state === 'done') {
        stopPolling();
        showToast('✅ 采集完成：新品 ' + ((d.result && d.result.new) || 0) + ' 条 / 爆品 ' + ((d.result && d.result.hot) || 0) + ' 条');
        await loadPool();
      } else if (d.state === 'error') {
        stopPolling();
        showToast('❌ 采集失败：' + d.error);
      }
    } catch (e) { /* 401 已在 fetchStatus 处理 */ }
  }, 3000);
  pollNow();
}
async function pollNow() {
  try { const d = await fetchStatus(); renderStatus(d); } catch (e) {}
}
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
function renderStatus(d) {
  const bar = document.getElementById('progressBar');
  const label = document.getElementById('progressLabel');
  const step = document.getElementById('progressStep');
  const pct = document.getElementById('progressPct');
  const log = document.getElementById('collectLog');
  const stepNames = { prepare: '准备中', collect_new: '采集新品池', collect_hot: '采集爆品池', diff: '周环比去重', build_pool: '重建需求池看板', done: '完成', error: '采集失败' };
  const p = d.progress || 0;
  const stepName = stepNames[d.step] || d.step || '处理中…';
  if (bar) bar.style.width = p + '%';
  if (step) step.textContent = stepName;
  if (pct) pct.textContent = p + '%';
  if (label) label.textContent = stepName + ' · ' + p + '%' + (d.state === 'error' ? ' · 失败' : (d.state === 'done' ? ' · 已完成' : ''));
  if (log && d.logs) log.textContent = d.logs.slice(-600);
  if (bar) {
    if (d.state === 'error') bar.style.background = '#dc3545';
    else if (d.state === 'done') bar.style.background = '#28a745';
    else bar.style.background = 'linear-gradient(90deg,#2F5496,#28a745)';
  }
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
    showToast('✅ 已导入 ' + d.selected + ' 条（新增 ' + d.added + ' / 跳过 ' + d.skipped + '），需求池已移除 ' + asins.length + ' 条');
    // 转入成功后：从需求池产品行中移除已转入的 ASIN，并刷新统计/可见数
    const importedSet = new Set(asins);
    POOLS[pool] = POOLS[pool].filter(p => !importedSet.has(p.asin));
    renderPool(pool);
    document.getElementById(pool + 'Total').textContent = POOLS[pool].length;
    updateCheckCount(pool);
    applyFilters(pool);
    buildCatNav();
  } catch (e) { showToast(e.message); }
}

// ============ 在线版：数据刷新 ============
async function loadPool() {
  try {
    const d = await api('/api/pool');
    // 已转入追踪看板的产品（服务端标记 _imported）从需求池行中隐藏
    POOLS.new = ((d.new && d.new.products) || []).filter(x => !x._imported);
    POOLS.hot = ((d.hot && d.hot.products) || []).filter(x => !x._imported);
    document.getElementById('newTotal').textContent = POOLS.new.length;
    document.getElementById('hotTotal').textContent = POOLS.hot.length;
    ['new', 'hot'].forEach(p => {
      const labels = new Set();
      POOLS[p].forEach(x => { if (x.__label__) labels.add(x.__label__); });
      // 类目筛选走左侧类目树(catSelection)，不再重建顶部类目下拉
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


TEMPLATE_POOL = '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>DuraTech 需求池看板 __WEEK__</title>\n<style>\n\n* { margin: 0; padding: 0; box-sizing: border-box; }\nbody { font-family: "Microsoft YaHei", "微软雅黑", Arial, sans-serif; font-size: 13px; background: #f0f2f5; color: #333; }\n\n/* 顶栏：深蓝渐变（传统风格） */\n.header { position: sticky; top: 0; z-index: 50; background: linear-gradient(135deg, #1a3a5c, #2F5496); color: #fff; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }\n.header .brand-block { display: flex; flex-direction: column; gap: 3px; min-width: 0; }\n.header .brand { font-size: 17px; font-weight: bold; display: flex; align-items: center; }\n.header .brand .logo { display: inline-flex; width: 26px; height: 26px; border-radius: 6px; background: rgba(255,255,255,0.22); color: #fff; font-weight: 700; align-items: center; justify-content: center; margin-right: 8px; font-size: 14px; }\n.header .sub { font-size: 11px; color: rgba(255,255,255,0.78); font-weight: 400; line-height: 1.4; }\n.header .sub b { color: #fff; font-weight: 600; }\n\n/* 顶栏右侧按钮（Cookie / 用户 / 退出 / 用户身份） */\n.hb-btn { padding: 6px 14px; border-radius: 4px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; white-space: nowrap; }\n.hb-btn.outline { background: transparent; color: #fff; border: 1px solid rgba(255,255,255,0.5); }\n.hb-btn.outline:hover { background: rgba(255,255,255,0.15); }\n.hb-btn.danger { background: #dc3545; color: #fff; border: none; }\n.hb-btn.danger:hover { background: #c82333; }\n.hb-user { font-size: 12px; color: #fff; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); padding: 6px 14px; border-radius: 4px; font-weight: 500; }\n/* 顶栏右侧缩放控件（自适应） */\n.header-right { display: flex; align-items: center; gap: 10px; }\n.zoom-ctrl { display: flex; align-items: center; gap: 4px; background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.3); border-radius: 20px; padding: 4px 8px; }\n.zoom-label { font-size: 11px; color: rgba(255,255,255,0.85); margin-right: 2px; }\n.zoom-val { font-size: 12px; color: #fff; min-width: 40px; text-align: center; font-weight: 600; }\n.zb { width: 22px; height: 22px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.4); background: rgba(255,255,255,0.12); color: #fff; cursor: pointer; font-size: 14px; line-height: 1; display: flex; align-items: center; justify-content: center; font-family: inherit; }\n.zb:hover { background: rgba(255,255,255,0.28); }\n.hb-user b { color: #ffd966; font-weight: 700; margin-left: 2px; }\n\n/* 看板切换导航（需求池 / 产品追踪） */\n.topnav { display: flex; gap: 10px; padding: 0 24px; background: linear-gradient(135deg, #16314f, #24447e); }\n.nav-tab { display: inline-flex; align-items: center; gap: 6px; padding: 11px 22px; color: rgba(255,255,255,0.7); text-decoration: none; font-size: 14px; font-weight: 600; border-bottom: 3px solid transparent; transition: all .15s; white-space: nowrap; }\n.nav-tab:hover { color: #fff; text-decoration: none; }\n.nav-tab.active { color: #fff; background: rgba(255,255,255,0.10); border-bottom-color: #4da3ff; }\n\n/* 布局：左侧导航（工具栏置顶 + 四大类目）+ 右侧内容，各自独立滚动 */\n.layout { display: flex; height: calc(100vh - 98px); overflow: hidden; }\n.sidebar { width: 320px; min-width: 320px; background: #fff; border-right: 1px solid #e0e0e0; display: flex; flex-direction: column; }\n\n/* 左侧置顶工具栏（标签/搜索/全选/导出/转入/显示） */\n.side-tools { padding: 12px 14px; border-bottom: 1px solid #e0e0e0; background: #fafafa; display: flex; flex-direction: column; gap: 8px; }\n.side-tools .inp { width: 100%; padding: 7px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; background: #fff; font-family: inherit; }\n.side-tools .inp:focus { outline: none; border-color: #2F5496; box-shadow: 0 0 0 2px rgba(47,84,150,0.15); }\n.side-tools .tool-btns { display: flex; gap: 6px; }\n.side-tools .tool-btns .btn { flex: 1; padding: 7px 0; font-size: 11px; }\n.side-tools .count { font-size: 11px; color: #666; }\n.side-tools .count b { color: #2F5496; }\n\n/* 左侧类目导航 */\n.sidebar-head { padding: 12px 16px; border-bottom: 1px solid #e0e0e0; font-size: 13px; font-weight: bold; color: #2F5496; background: #f8f9fa; }\n.cat-nav { flex: 1; overflow-y: auto; padding: 8px 10px; }\n.cat-item { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 10px 12px; margin-bottom: 4px; border: none; background: transparent; color: #333; font-size: 12px; font-weight: 500; border-radius: 6px; cursor: pointer; font-family: inherit; text-align: left; }\n.cat-item .cname { flex: 1; min-width: 0; word-wrap: break-word; line-height: 1.4; }\n.cat-item .ccnt { margin-left: 8px; font-size: 11px; color: #999; font-weight: 600; }\n.cat-item:hover { background: #f0f2f5; }\n.cat-item.active { background: #2F5496; color: #fff; font-weight: 600; }\n.cat-item.active .ccnt { color: rgba(255,255,255,0.8); }\n\n/* 细分类目分组 */\n.cat-group { margin-bottom: 4px; }\n.cat-l1-title { padding: 8px 12px 4px; font-size: 11px; font-weight: 700; color: #2F5496; border-bottom: 1px solid #e8e8e8; display: flex; justify-content: space-between; align-items: center; cursor: default; }\n.cat-l1-title .ccnt { font-size: 10px; color: #999; font-weight: 400; }\n.cat-sub { padding-left: 20px !important; font-size: 11px; }\n\n.main { flex: 1; min-width: 0; overflow: auto; padding: 16px 24px; }\n\n/* 分段控件（新品/爆品） */\n.seg { display: inline-flex; background: #e9ecef; border-radius: 8px; padding: 3px; margin-bottom: 14px; }\n.seg .sbtn { padding: 7px 18px; border: none; background: transparent; border-radius: 6px; font-size: 13px; font-weight: bold; color: #666; cursor: pointer; font-family: inherit; }\n.seg .sbtn.active { background: #fff; color: #2F5496; box-shadow: 0 1px 3px rgba(0,0,0,0.12); }\n\n/* Tab 面板显隐：仅 active 面板可见，切换才生效 */\n.tab-panel { display: none; }\n.tab-panel.active { display: block; }\n\n/* 统计卡片 */\n.stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 12px; }\n.stat-card { background: #f8f9fa; border-radius: 8px; padding: 14px; text-align: center; cursor: pointer; transition: transform .15s, box-shadow .15s; border: 2px solid transparent; user-select: none; }\n.stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }\n.stat-card.active { border-color: #2F5496; background: #eef2f9; }\n.stat-card .num { font-size: 24px; font-weight: bold; color: #2F5496; }\n.stat-card .label { font-size: 11px; color: #888; margin-top: 4px; }\n\n/* 细分类目统计行 */\n.cat-stats-row { background: linear-gradient(135deg, #eef4fb, #e3edf9); border: 1px solid #c5d8f0; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; }\n.cat-stats-title { font-size: 13px; font-weight: 700; color: #2F5496; margin-bottom: 8px; }\n.cat-stats-cards { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }\n.cat-stats-cards .stat-card { background: #fff; }\n\n/* 工具栏 */\n.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; background: #fff; padding: 10px 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }\n.toolbar .inp { padding: 6px 12px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; background: #fff; font-family: inherit; }\n.toolbar .inp:focus { outline: none; border-color: #2F5496; box-shadow: 0 0 0 2px rgba(47,84,150,0.15); }\n.btn { padding: 7px 16px; border: none; border-radius: 4px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; background: #6c757d; color: #fff; }\n.btn:hover { background: #5a6268; }\n.btn.primary { background: #2F5496; color: #fff; }\n.btn.primary:hover { background: #1e3a6e; }\n.btn.green { background: #28a745; color: #fff; }\n.btn.green:hover { background: #1e7e34; }\n\n/* 表格 */\n.table-card { background: #fff; border-radius: 8px; overflow: visible; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }\n.table-card::-webkit-scrollbar { height: 8px; }\n.table-card::-webkit-scrollbar-thumb { background: #c5d4e8; border-radius: 4px; }\n.table-card::-webkit-scrollbar-track { background: #f0f2f5; }\ntable { width: 100%; min-width: 1080px; border-collapse: separate; border-spacing: 0; }\nthead { position: sticky; top: 0; z-index: 10; }\nth { background: #2F5496; color: #fff; padding: 10px 6px; font-size: 11px; font-weight: 600; text-align: center; white-space: nowrap; border-bottom: 2px solid #1a3a5c; }\ntd { padding: 10px 6px; border-bottom: 1px solid #eee; font-size: 11px; text-align: center; vertical-align: middle; position: relative; z-index: 1; }\ntr:last-child td { border-bottom: none; }\ntr:hover { background: #f8f9ff; }\ntr.filtered { background: #eef2f9; }\nimg.product-img { width: 100px; height: 100px; object-fit: contain; border: 1px solid #eee; border-radius: 4px; background: #fafafa; }\n.title-cell { max-width: 240px; word-wrap: break-word; text-align: left; }\n.num-cell { text-align: right; white-space: nowrap; }\n.price-cell { color: #c00; font-weight: bold; }\n.rating { color: #f0ad4e; font-weight: bold; }\na { color: #2F5496; text-decoration: none; }\na:hover { text-decoration: underline; }\n.growth-note { font-size: 10px; color: #198754; white-space: nowrap; }\n.growth-note.new { color: #0d6efd; }\n.toast { position: fixed; top: 20px; right: 20px; background: #28a745; color: #fff; padding: 10px 20px; border-radius: 4px; z-index: 9999; display: none; font-size: 13px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }\n/* 横向滚动控制条（表格底部左右滑动） */\n.hscroll-bar { display: none; align-items: center; justify-content: center; gap: 12px; margin-top: 10px; }\n.hscroll-bar.show { display: flex; }\n.hscroll-btn { display: inline-flex; align-items: center; gap: 6px; padding: 7px 18px; border: 1px solid #2F5496; background: #2F5496; color: #fff; border-radius: 20px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; transition: all .15s; }\n.hscroll-btn:hover { background: #1e3a6e; }\n.hscroll-btn:disabled { background: #c5d4e8; border-color: #c5d4e8; cursor: not-allowed; }\n.hscroll-bar .hint { font-size: 11px; color: #888; }\n@media (max-width: 1200px) { .stats-row { grid-template-columns: repeat(2, 1fr); } .sidebar { width: 280px; min-width: 280px; } .cat-stats-cards { grid-template-columns: repeat(3, 1fr); } }\n@media (max-width: 1000px) { .table-card table { min-width: 1080px; } .main { padding: 12px 14px; } }\n@media (max-width: 768px) {\n  .layout { flex-direction: column; height: auto; overflow: visible; }\n  .sidebar { width: 100%; min-width: 0; max-height: 320px; }\n  .main { overflow: visible; }\n  .stats-row { grid-template-columns: repeat(2, 1fr); }\n  .cat-stats-cards { grid-template-columns: repeat(2, 1fr); }\n  .table-card table { min-width: 980px; }\n}\n\n</style>\n</head>\n<body>\n\n\n<div class="header">\n  <div class="brand-block">\n    <div class="brand"><span class="logo">D</span>DuraTech 需求池看板</div>\n    <div class="sub">周次: <b>__WEEK__</b> · 生成于 __DATE__ · 勾选产品后可转入追踪看板</div>\n  </div>\n  <div class="header-right">\n    <div class="zoom-ctrl">\n      <span class="zoom-label">缩放</span>\n      <button class="zb" onclick="zoomOut()" title="缩小">−</button>\n      <span id="zoomVal" class="zoom-val">100%</span>\n      <button class="zb" onclick="zoomIn()" title="放大">+</button>\n      <button class="zb" onclick="zoomReset()" title="重置">⟳</button>\n    </div>\n    <div id="headerRightArea"></div>\n  </div>\n</div>\n\n<div class="topnav">\n  <a href="/" class="nav-tab active">📋 需求池看板</a>\n  <a href="/tracking" class="nav-tab">📊 产品追踪看板 →</a>\n</div>\n\n\n\n<div class="layout">\n  <aside class="sidebar">\n    <div class="side-tools">\n      <input class="inp filter-search" type="text" placeholder="🔍 搜索 ASIN/品牌/标题..." oninput="applyFilters(activePool)">\n      <div class="tool-btns">\n        <button class="btn" onclick="toggleAll(activePool)">☑ 全选</button>\n        <button class="btn" onclick="exportSelectedCSV(activePool)">📥 导出</button>\n        <button class="btn green" onclick="transferToDashboard(activePool)">📤 转入</button>\n      </div>\n      <div class="count">显示: <b id="visibleCount">0</b>/<b id="totalCount">0</b></div>\n    </div>\n    <div class="sidebar-head">📂 细分类目筛选</div>\n    <nav class="cat-nav" id="catNav"></nav>\n  </aside>\n\n  <main class="main">\n    <div class="seg">\n      <button class="sbtn active" onclick="switchTab(\'new\')">🆕 新品需求池 <b id="newCount">__NEW_TOTAL__</b></button>\n      <button class="sbtn" onclick="switchTab(\'hot\')">🔥 爆品需求池 <b id="hotCount">__HOT_TOTAL__</b></button>\n    </div>\n\n    <!-- 细分类目统计行（选中细分类目后显示） -->\n    <div class="cat-stats-row" id="catStatsRow" style="display:none">\n      <div class="cat-stats-title" id="catStatsTitle"></div>\n      <div class="cat-stats-cards">\n        <div class="stat-card"><div class="num" id="catTotal">0</div><div class="label">该类目产品总数</div></div>\n        <div class="stat-card"><div class="num" id="catNew" style="color:#0d6efd">0</div><div class="label">🆕 新上架产品数</div></div>\n        <div class="stat-card"><div class="num" id="catGrew" style="color:#198754">0</div><div class="label">📈 销量增长产品数</div></div>\n        <div class="stat-card"><div class="num" id="catSales">0</div><div class="label">近30天总销量</div></div>\n        <div class="stat-card"><div class="num" id="catMonthly">0</div><div class="label">总月销售额</div></div>\n      </div>\n    </div>\n\n    <!-- 新品池 -->\n    <div class="tab-panel active" id="tab-new">\n      <div class="stats-row" id="newStatsRow">\n        <div class="stat-card" onclick="filterByGrowth(\'new\', null)"><div class="num" id="newTotal">__NEW_TOTAL__</div><div class="label">产品总数</div></div>\n        <div class="stat-card" id="newCardNew" onclick="filterByGrowth(\'new\', \'new\')"><div class="num" id="newNew" style="color:#2F5496">__NEW_NEW__</div><div class="label">🆕 新上架</div></div>\n        <div class="stat-card" id="newCardGrew" onclick="filterByGrowth(\'new\', \'grew\')"><div class="num" id="newGrew" style="color:#198754">__NEW_GREW__</div><div class="label">📈 销量增长</div></div>\n        <div class="stat-card"><div class="num" id="newSelected" style="color:#2F5496">0</div><div class="label">已勾选</div></div>\n      </div>\n      <div class="table-card">\n        <table><thead><tr>\n          <th style="width:28px"><input type="checkbox" class="check-all" data-pool="new" onchange="toggleAll(\'new\')" title="全选"></th>\n          <th style="width:110px">主图</th><th>ASIN</th><th style="width:70px">品牌</th><th>标题</th>\n          <th>近30天销量</th><th>月销售额</th><th>售价</th><th>上架时间</th><th>评分</th><th>评论</th><th>BSR</th><th>变体</th><th>📝 备注</th>\n        </tr></thead>\n        <tbody id="newBody"></tbody></table>\n      </div>\n      <div class="hscroll-bar" id="hscroll-new" data-target="new">\n        <button class="hscroll-btn" onclick="hScroll(\'new\', -1)" id="hscroll-left-new">← 向左</button>\n        <span class="hint">拖动查看未显示的产品信息</span>\n        <button class="hscroll-btn" onclick="hScroll(\'new\', 1)" id="hscroll-right-new">向右 →</button>\n      </div>\n    </div>\n\n    <!-- 爆品池 -->\n    <div class="tab-panel" id="tab-hot">\n      <div class="stats-row" id="hotStatsRow">\n        <div class="stat-card" onclick="filterByGrowth(\'hot\', null)"><div class="num" id="hotTotal">__HOT_TOTAL__</div><div class="label">产品总数</div></div>\n        <div class="stat-card" id="hotCardNew" onclick="filterByGrowth(\'hot\', \'new\')"><div class="num" id="hotNew" style="color:#2F5496">__HOT_NEW__</div><div class="label">🆕 新上架</div></div>\n        <div class="stat-card" id="hotCardGrew" onclick="filterByGrowth(\'hot\', \'grew\')"><div class="num" id="hotGrew" style="color:#198754">__HOT_GREW__</div><div class="label">📈 销量增长</div></div>\n        <div class="stat-card"><div class="num" id="hotSelected" style="color:#2F5496">0</div><div class="label">已勾选</div></div>\n      </div>\n      <div class="table-card">\n        <table><thead><tr>\n          <th style="width:28px"><input type="checkbox" class="check-all" data-pool="hot" onchange="toggleAll(\'hot\')" title="全选"></th>\n          <th style="width:110px">主图</th><th>ASIN</th><th style="width:70px">品牌</th><th>标题</th>\n          <th>近30天销量</th><th>月销售额</th><th>售价</th><th>上架时间</th><th>评分</th><th>评论</th><th>BSR</th><th>变体</th><th>📝 备注</th>\n        </tr></thead>\n        <tbody id="hotBody"></tbody></table>\n      </div>\n      <div class="hscroll-bar" id="hscroll-hot" data-target="hot">\n        <button class="hscroll-btn" onclick="hScroll(\'hot\', -1)" id="hscroll-left-hot">← 向左</button>\n        <span class="hint">拖动查看未显示的产品信息</span>\n        <button class="hscroll-btn" onclick="hScroll(\'hot\', 1)" id="hscroll-right-hot">向右 →</button>\n      </div>\n    </div>\n  </main>\n</div>\n\n<div class="toast" id="toast"></div>\n\n__HEADER_EXTRA__\n\n<script>\nconst POOLS = {\n  new: __NEW_JSON__,\n  hot: __HOT_JSON__\n};\nconst LABEL_COLORS = __LABEL_COLORS__;\n\n\nlet catSelection = \'\';\nlet activePool = \'new\';\n\n// ===== 细分类目树（从 Python config 注入） =====\nconst SUB_CAT_TREE = __SUB_CAT_TREE__;\n// 扁平化所有目标细分类目名称（用于侧栏展示）\nfunction flattenTree(tree) {\n  const items = [];\n  for (const [l1, subs] of Object.entries(tree)) {\n    for (const s of subs) items.push({ l1, ...s });\n  }\n  return items;\n}\nconst ALL_SUB_CATS = flattenTree(SUB_CAT_TREE);\n\n// ===== Tab 切换 =====\nfunction switchTab(tab) {\n  activePool = tab;\n  document.querySelectorAll(\'.seg .sbtn\').forEach(b => b.classList.remove(\'active\'));\n  document.querySelectorAll(\'.seg .sbtn\')[tab === \'new\' ? 0 : 1].classList.add(\'active\');\n  document.querySelectorAll(\'.tab-panel\').forEach(c => c.classList.remove(\'active\'));\n  document.getElementById(\'tab-\' + tab).classList.add(\'active\');\n  // 切换池时重置筛选，给干净视图\n  catSelection = \'\';\n  document.querySelector(\'.filter-search\').value = \'\';\n  buildCatNav();\n  applyFilters(tab);\n  updateCatStats(tab);\n  updateHScroll(tab);\n}\n\n// ===== HTML 转义 =====\nfunction esc(s) { return (s || \'\').replace(/&/g, \'&amp;\').replace(/"/g, \'&quot;\').replace(/\'/g, \'&#39;\'); }\nfunction escapeHtml(s) { return esc(s); }\n\n// ===== 左侧导航：细分类目树 =====\nfunction buildCatNav() {\n  const nav = document.getElementById(\'catNav\');\n  const pool = POOLS[activePool];\n  const total = pool.length;\n  let html = \'\';\n\n  // 「全部产品」置顶\n  html += \'<button class="cat-item\' + (catSelection === \'\' ? \' active\' : \'\') + \'" data-cat="" onclick="pickCat(this)"><span class="cname">🏠 全部产品</span><span class="ccnt">\' + total + \'</span></button>\';\n\n  // 按一级类目分组，每组下挂细分类目\n  for (const [l1, subs] of Object.entries(SUB_CAT_TREE)) {\n    // 一级类目标题（不可点击，仅分组标题）\n    const l1Cnt = pool.filter(p => (p.category || p.fine_category || \'\') === l1 ||\n      (p.category_l1 || \'\') === l1 || subs.some(s => (p.fine_category || p.category_leaf || p.category_l2 || \'\').toLowerCase() === s.name.toLowerCase())).length;\n    html += \'<div class="cat-group"><div class="cat-l1-title">\' + esc(l1) + \'<span class="ccnt">\' + l1Cnt + \'</span></div>\';\n    // 细分类目按钮\n    for (const s of subs) {\n      // 匹配策略：fine_category > category_leaf > category_l3 > category_l2 （大小写不敏感）\n      const sNameLower = s.name.toLowerCase();\n      const cnt = pool.filter(p => {\n        const fc = (p.fine_category || p.category_leaf || p.category_l3 || p.category_l2 || \'\').toLowerCase();\n        const pL1 = (p.category_l1 || p.category || \'\').toLowerCase();\n        return fc === sNameLower && pL1 === l1.toLowerCase();\n      }).length;\n      const label = s.cn ? s.name + \' (\' + s.cn + \')\' : s.name;\n      const catKey = l1 + \'::\' + s.name;\n      const isActive = catSelection === catKey;\n      html += \'<button class="cat-item cat-sub\' + (isActive ? \' active\' : \'\') + \'" data-cat="\' + esc(catKey) + \'" onclick="pickCat(this)" title="\' + esc(label) + \'"><span class="cname">\' + esc(label) + \'</span><span class="ccnt">\' + cnt + \'</span></button>\';\n    }\n    html += \'</div>\';  // end cat-group\n  }\n  nav.innerHTML = html;\n}\n\nfunction pickCat(btn) {\n  catSelection = btn.dataset.cat || \'\';\n  buildCatNav();\n  applyFilters(activePool);\n  updateCatStats(activePool);\n}\n\n// ===== 渲染表格 =====\nfunction createRow(p, pool) {\n  const tr = document.createElement(\'tr\');\n  // 仅 image 走可信来源（亚马逊官方图床），其余字段一律 escapeHtml 防止 XSS\n  const img = p.image ? \'<img class="product-img" src="\' + escapeHtml(p.image) + \'" loading="lazy">\' : \'<img class="product-img" src="" style="visibility:hidden">\';\n  tr.dataset.category = p.category_l1 || p.category || \'\';\n  // 细分类目（用于侧栏筛选）：优先 fine_category > category_leaf > category_l3 > category_l2 > category\n  tr.dataset.fineCategory = (p.fine_category || p.category_leaf || p.category_l3 || p.category_l2 || p.category || \'\');\n  const growthClass = (p._growth_note || \'\').startsWith(\'🆕\') ? \'new\' : \'\';\n  tr.innerHTML = \'<td style="text-align:center"><input type="checkbox" class="row-cb" data-asin="\' + escapeHtml(p.asin) + \'" data-pool="\' + pool + \'" onchange="updateCheckCount(this.dataset.pool)"\' + (p._imported ? \' disabled\' : \'\') + \'></td>\'\n    + (p._imported ? \'<td style="opacity:0.45">\' + img + \'</td>\' : \'<td>\' + img + \'</td>\')\n    + \'<td><a href="https://www.amazon.com/dp/\' + escapeHtml(p.asin) + \'" target="_blank">\' + escapeHtml(p.asin) + \'</a></td>\'\n    + \'<td>\' + escapeHtml(p.brand || \'\') + \'</td>\'\n    + \'<td class="title-cell" title="\' + escapeHtml(p.title || \'\') + \'">\' + escapeHtml(p.title || \'\') + \'</td>\'\n    + \'<td class="num-cell">\' + escapeHtml(p.sales || \'\') + \'</td>\'\n    + \'<td class="num-cell">\' + escapeHtml(p.monthly_sales || \'\') + \'</td>\'\n    + \'<td class="num-cell price-cell">\' + escapeHtml(p.price || \'\') + \'</td>\'\n    + \'<td>\' + escapeHtml(p.available || \'\') + \'</td>\'\n    + \'<td class="num-cell rating">\' + escapeHtml(p.rating || \'\') + \'</td>\'\n    + \'<td class="num-cell">\' + escapeHtml(p.reviews || \'\') + \'</td>\'\n    + \'<td class="num-cell">\' + escapeHtml(p.bsr || \'\') + \'</td>\'\n    + \'<td class="num-cell">\' + escapeHtml(p.variants || \'\') + \'</td>\'\n    + \'<td><span class="growth-note \' + growthClass + \'">\' + escapeHtml(p._growth_note || \'\') + \'</span></td>\';\n  return tr;\n}\n\nfunction renderPool(pool) {\n  const tbody = document.getElementById(pool + \'Body\');\n  tbody.innerHTML = \'\';\n  POOLS[pool].forEach(p => tbody.appendChild(createRow(p, pool)));\n}\n\n// ===== 筛选 =====\nconst growthFilter = {};\n\nfunction applyFilters(pool) {\n  const fs = document.querySelector(\'.filter-search\').value.toLowerCase();\n  const gf = growthFilter[pool] || null;\n  const tbody = document.getElementById(pool + \'Body\');\n  const rows = tbody.querySelectorAll(\'tr\');\n  let visible = 0;\n  // 细分类目筛选：大小写不敏感匹配\n  let selL1 = \'\', selSub = \'\';\n  if (catSelection) {\n    const parts = catSelection.split(\'::\');\n    selL1 = (parts[0] || \'\').toLowerCase();\n    selSub = (parts[1] || \'\').toLowerCase();\n  }\n  rows.forEach(row => {\n    const fineCat = (row.dataset.fineCategory || \'\').toLowerCase();\n    const asin = (row.querySelector(\'a\')?.textContent || \'\').toLowerCase();\n    const brand = (row.cells[3]?.textContent || \'\').toLowerCase();\n    const title = (row.querySelector(\'.title-cell\')?.textContent || \'\').toLowerCase();\n    const growthNote = (row.querySelector(\'.growth-note\')?.textContent || \'\').trim();\n    let show = true;\n    if (selSub && (fineCat !== selSub || (selL1 && (row.dataset.category || \'\').toLowerCase() !== selL1))) show = false;\n    if (fs && !(asin.includes(fs) || brand.includes(fs) || title.includes(fs))) show = false;\n    if (gf === \'new\' && !growthNote.startsWith(\'🆕\')) show = false;\n    if (gf === \'grew\' && !growthNote.startsWith(\'📈\')) show = false;\n    row.style.display = show ? \'\' : \'none\';\n    if (show) visible++;\n  });\n  if (pool === activePool) {\n    document.getElementById(\'visibleCount\').textContent = visible;\n    document.getElementById(\'totalCount\').textContent = POOLS[pool].length;\n  }\n}\n\n// ===== 细分类目统计（选中细分类目后自动统计该类目指标） =====\nfunction parseNum(v) {\n  if (v === null || v === undefined || v === \'\') return 0;\n  const n = parseFloat(String(v).replace(/[, ]/g, \'\'));\n  return isNaN(n) ? 0 : n;\n}\nfunction fmtNum(v) { return Math.round(v).toLocaleString(\'en-US\'); }\n\nfunction fineCatOf(p) {\n  return (p.fine_category || p.category_leaf || p.category_l3 || p.category_l2 || p.category || \'\').toLowerCase();\n}\n\nfunction updateCatStats(pool) {\n  const catRow = document.getElementById(\'catStatsRow\');\n  const origRow = document.getElementById(pool + \'StatsRow\');\n  const title = document.getElementById(\'catStatsTitle\');\n  const sel = (catSelection || \'\').trim();\n  if (!sel) {\n    catRow.style.display = \'none\';\n    if (origRow) origRow.style.display = \'\';\n    return;\n  }\n  const parts = sel.split(\'::\');\n  const selL1 = (parts[0] || \'\').toLowerCase();\n  const selSub = (parts[1] || \'\').toLowerCase();\n  const matched = POOLS[pool].filter(p => {\n    const pL1 = (p.category_l1 || p.category || \'\').toLowerCase();\n    return fineCatOf(p) === selSub && (!selL1 || pL1 === selL1);\n  });\n  let newCnt = 0, grewCnt = 0, totalSales = 0, totalMonthly = 0;\n  matched.forEach(p => {\n    const note = (p._growth_note || \'\');\n    if (note.startsWith(\'🆕\')) newCnt++;\n    if (note.startsWith(\'📈\')) grewCnt++;\n    totalSales += parseNum(p.sales);\n    totalMonthly += parseNum(p.monthly_sales);\n  });\n  const titleName = (parts[1] || sel);\n  title.textContent = \'📊 \' + titleName + \' · 本次需求池统计（\' + (pool === \'new\' ? \'新品\' : \'爆品\') + \'）\';\n  document.getElementById(\'catTotal\').textContent = matched.length;\n  document.getElementById(\'catNew\').textContent = newCnt;\n  document.getElementById(\'catGrew\').textContent = grewCnt;\n  document.getElementById(\'catSales\').textContent = fmtNum(totalSales);\n  document.getElementById(\'catMonthly\').textContent = \'$\' + fmtNum(totalMonthly);\n  catRow.style.display = \'block\';\n  // 选中细分类目时隐藏原有的全池统计行，避免重复\n  if (origRow) origRow.style.display = \'none\';\n}\n\nfunction filterByGrowth(pool, type) {\n  if (type === null) {\n    growthFilter[pool] = null;\n    document.getElementById(pool + \'CardNew\').classList.remove(\'active\');\n    document.getElementById(pool + \'CardGrew\').classList.remove(\'active\');\n    applyFilters(pool); return;\n  }\n  if (growthFilter[pool] === type) {\n    growthFilter[pool] = null;\n    document.getElementById(pool + \'CardNew\').classList.remove(\'active\');\n    document.getElementById(pool + \'CardGrew\').classList.remove(\'active\');\n  } else {\n    growthFilter[pool] = type;\n    document.getElementById(pool + \'CardNew\').classList.toggle(\'active\', type === \'new\');\n    document.getElementById(pool + \'CardGrew\').classList.toggle(\'active\', type === \'grew\');\n  }\n  applyFilters(pool);\n}\n\nfunction toggleAll(pool) {\n  const checkAll = document.querySelector(\'.check-all[data-pool="\' + pool + \'"]\');\n  const rows = document.querySelectorAll(\'#\' + pool + \'Body tr\');\n  let anyChecked = false;\n  rows.forEach(row => { if (row.style.display !== \'none\' && row.querySelector(\'.row-cb\').checked) anyChecked = true; });\n  const targetState = !anyChecked;\n  rows.forEach(row => { if (row.style.display !== \'none\') row.querySelector(\'.row-cb\').checked = targetState; });\n  checkAll.checked = targetState;\n  updateCheckCount(pool);\n}\n\nfunction updateCheckCount(pool) {\n  const cbs = document.querySelectorAll(\'#\' + pool + \'Body .row-cb:checked\');\n  document.getElementById(pool + \'Selected\').textContent = cbs.length;\n}\n\nfunction exportSelectedCSV(pool) {\n  const cbs = document.querySelectorAll(\'#\' + pool + \'Body .row-cb:checked\');\n  if (cbs.length === 0) { showToast(\'请先勾选产品\'); return; }\n  const headers = [\'类目\',\'ASIN\',\'品牌\',\'标题\',\'来源\',\'近30天销量\',\'月销售额\',\'售价\',\'上架时间\',\'评分\',\'评论数\',\'BSR\',\'变体数\',\'主图链接\',\'备注\'];\n  const selected = [];\n  cbs.forEach(cb => {\n    const p = POOLS[pool].find(x => x.asin === cb.dataset.asin);\n    if (p) selected.push([p.category||\'\', p.asin, p.brand||\'\', p.title||\'\',\n      p._source||\'\', p.sales||\'\', p.monthly_sales||\'\', p.price||\'\', p.available||\'\',\n      p.rating||\'\', p.reviews||\'\', p.bsr||\'\', p.variants||\'\', p.image||\'\', p._growth_note||\'\']);\n  });\n  let csv = \'\\uFEFF\' + headers.join(\',\') + \'\\n\';\n  selected.forEach(r => csv += r.map(v => \'"\' + (v||\'\').replace(/"/g, \'""\') + \'"\').join(\',\') + \'\\n\');\n  const blob = new Blob([csv], { type: \'text/csv;charset=utf-8\' });\n  const url = URL.createObjectURL(blob);\n  const a = document.createElement(\'a\');\n  a.href = url; a.download = \'DuraTech_\' + (pool === \'new\' ? \'新品\' : \'爆品\') + \'_勾选_\' + new Date().toISOString().slice(0,10) + \'.csv\';\n  a.click(); URL.revokeObjectURL(url);\n  showToast(\'已导出 \' + selected.length + \' 条\');\n}\n\nfunction transferToDashboard(pool) {\n  const cbs = document.querySelectorAll(\'#\' + pool + \'Body .row-cb:checked\');\n  if (cbs.length === 0) { showToast(\'请先勾选要转入的产品\'); return; }\n  if (!confirm(\'确定将 \' + cbs.length + \' 个产品转入 DuraTech 产品追踪看板吗？\')) return;\n  const selected = [];\n  cbs.forEach(cb => {\n    const p = POOLS[pool].find(x => x.asin === cb.dataset.asin);\n    if (p) {\n      p.__label__ = p.__label__ || (pool === \'new\' ? \'潜力新品\' : \'标准爆品\');\n      p._source = p._source || (pool === \'new\' ? \'new\' : \'hot\');\n      selected.push(p);\n    }\n  });\n  const json = JSON.stringify({ pool: pool, products: selected, transfer_time: new Date().toISOString() }, null, 2);\n  const blob = new Blob([json], { type: \'application/json;charset=utf-8\' });\n  const url = URL.createObjectURL(blob);\n  const a = document.createElement(\'a\');\n  a.href = url; a.download = \'pending_transfer_\' + new Date().toISOString().slice(0,10) + \'.json\';\n  a.click(); URL.revokeObjectURL(url);\n  showToast(\'已导出 \' + selected.length + \' 条转入文件！请将下载的 JSON 发给我，我会自动更新追踪看板\');\n  cbs.forEach(cb => { cb.parentElement.parentElement.style.opacity = \'0.4\'; cb.disabled = true; });\n}\n\nfunction showToast(msg) {\n  const t = document.getElementById(\'toast\');\n  t.textContent = msg; t.style.display = \'block\';\n  setTimeout(() => t.style.display = \'none\', 3000);\n}\n\n// ===== 页面缩放（自适应分辨率 / 缩放大小） =====\nlet currentZoom = parseFloat(localStorage.getItem(\'dt_zoom\') || \'1\') || 1;\nfunction applyZoom() {\n  document.documentElement.style.zoom = currentZoom;\n  const z = document.getElementById(\'zoomVal\');\n  if (z) z.textContent = Math.round(currentZoom * 100) + \'%\';\n}\nfunction zoomIn() { currentZoom = Math.min(1.8, Math.round((currentZoom + 0.1) * 10) / 10); localStorage.setItem(\'dt_zoom\', currentZoom); applyZoom(); }\nfunction zoomOut() { currentZoom = Math.max(0.6, Math.round((currentZoom - 0.1) * 10) / 10); localStorage.setItem(\'dt_zoom\', currentZoom); applyZoom(); }\nfunction zoomReset() { currentZoom = 1; localStorage.removeItem(\'dt_zoom\'); applyZoom(); }\n\n// ===== 横向滚动控制（查看未显示全的产品信息） =====\nfunction hScroll(pool, dir) {\n  const card = document.querySelector(\'.main\');\n  if (!card) return;\n  const step = Math.max(200, Math.round(card.clientWidth * 0.6));\n  card.scrollBy({ left: dir * step, behavior: \'smooth\' });\n  setTimeout(() => updateHScroll(pool), 350);\n}\n\nfunction updateHScroll(pool) {\n  const card = document.querySelector(\'.main\');\n  const bar = document.getElementById(\'hscroll-\' + pool);\n  if (!card || !bar) return;\n  const overflow = card.scrollWidth - card.clientWidth > 2;\n  bar.classList.toggle(\'show\', overflow);\n  if (!overflow) return;\n  const leftBtn = document.getElementById(\'hscroll-left-\' + pool);\n  const rightBtn = document.getElementById(\'hscroll-right-\' + pool);\n  if (leftBtn) leftBtn.disabled = card.scrollLeft <= 2;\n  if (rightBtn) rightBtn.disabled = card.scrollLeft + card.clientWidth >= card.scrollWidth - 2;\n}\n\n// ===== 初始化 =====\n[\'new\', \'hot\'].forEach(pool => renderPool(pool));\nbuildCatNav();\napplyZoom();\napplyFilters(\'new\');\nupdateHScroll(\'new\');\nupdateHScroll(\'hot\');\nwindow.addEventListener(\'resize\', () => { updateHScroll(activePool); });\n\n\n__SCRIPT_EXTRA__\n</script>\n</body>\n</html>'

def build_pool_dashboard(output_path=None, web_mode=False):
    """生成需求池看板 HTML（传统皮肤 + 左侧细分类目树 + 中英双语 + 缩放/横向滚动）
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
    sub_cat_tree_json = json.dumps(SUB_CATEGORIES, ensure_ascii=False)

    # 在线版注入额外 UI / JS
    header_extra = WEB_HEADER_EXTRA if web_mode else ""
    script_extra = WEB_SCRIPT_EXTRA if web_mode else ""

    html = TEMPLATE_POOL

    html = (html
        .replace("__WEEK__", week_label)
        .replace("__DATE__", date_str)
        .replace("__NEW_JSON__", new_json)
        .replace("__HOT_JSON__", hot_json)
        .replace("__LABEL_COLORS__", label_colors_json)
        .replace("__SUB_CAT_TREE__", sub_cat_tree_json)
        .replace("__HEADER_EXTRA__", header_extra)
        .replace("__NEW_NEW__", str(new_stats.get('new', 0)))
        .replace("__NEW_GREW__", str(new_stats.get('grew', 0)))
        .replace("__HOT_NEW__", str(hot_stats.get('new', 0)))
        .replace("__HOT_GREW__", str(hot_stats.get('grew', 0)))
        .replace("__NEW_TOTAL__", str(len(new_products)))
        .replace("__HOT_TOTAL__", str(len(hot_products)))
        .replace("__SCRIPT_EXTRA__", script_extra))

    Path(output_path).write_text(html, encoding='utf-8')
    print(f"[OK] 需求池看板已生成: {output_path}")
    print(f"     新品池: {len(new_products)} 条, 爆品池: {len(hot_products)} 条")
    return output_path


if __name__ == "__main__":
    build_pool_dashboard()
