"""
DuraTech 需求池看板在线版 - 账号鉴权模块
- 注册（首个用户自动成为 admin）/ 登录 / 登出
- token 会话（secrets.token_hex(32)，7 天有效）
- 装饰器: login_required / admin_required
"""
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import jsonify, request, g
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_conn

TOKEN_TTL_DAYS = 7


def _now():
    return datetime.now()


def register(username, password, is_admin=False):
    """注册用户；首个用户自动成为 admin。返回 (user, error)"""
    username = (username or "").strip()
    if not username or not password:
        return None, "用户名和密码不能为空"
    if len(password) < 6:
        return None, "密码至少 6 位"

    conn = get_conn()
    try:
        # 首个用户为管理员
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        is_admin = is_admin or count == 0
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
            (username, generate_password_hash(password), 1 if is_admin else 0))
        conn.commit()
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    except Exception:
        conn.rollback()
        conn.close()
        return None, "用户名已存在"
    conn.close()
    return {"id": uid, "username": username, "is_admin": is_admin}, None


def create_token(user_id):
    """为用户签发 token，返回 (token, expires_at)"""
    token = secrets.token_hex(32)
    expires = _now() + timedelta(days=TOKEN_TTL_DAYS)
    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
        (token, user_id, expires.isoformat()))
    conn.commit()
    conn.close()
    return token, expires


def login(username, password):
    """校验用户名密码，成功返回 (user, token, expires_at)"""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, username, password_hash, is_admin FROM users WHERE username=?",
        (username.strip(),)).fetchone()
    conn.close()
    if not row:
        return None, None, None
    if not check_password_hash(row["password_hash"], password):
        return None, None, None
    user = {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}
    token, expires = create_token(row["id"])
    return user, token, expires


def logout(token):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()


def get_user_by_token(token):
    """按 token 查用户；过期/不存在返回 None"""
    if not token:
        return None
    conn = get_conn()
    row = conn.execute(
        """SELECT u.id, u.username, u.is_admin FROM sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.token=? AND s.expires_at > ?""",
        (token, _now().isoformat())).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def _extract_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Access-Token", "")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        user = get_user_by_token(token)
        if not user:
            return jsonify({"ok": False, "error": "未登录或登录已过期"}), 401
        g.user = user
        g.token = token
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        user = get_user_by_token(token)
        if not user:
            return jsonify({"ok": False, "error": "未登录或登录已过期"}), 401
        if not user["is_admin"]:
            return jsonify({"ok": False, "error": "需要管理员权限"}), 403
        g.user = user
        g.token = token
        return fn(*args, **kwargs)
    return wrapper
