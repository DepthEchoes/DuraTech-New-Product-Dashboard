#!/usr/bin/env bash
# ============================================================
# DuraTech 看板 - 服务器一键部署脚本
# 适用: 阿里云轻量应用服务器 SWAS / 任意 Ubuntu 22.04 云主机
# 设计: 复刻沙箱目录结构 (/workspace/sellersprite-automation + /root/uploads)
#       代码零改动即可运行（代码中硬编码了上述路径）
#
# 用法:
#   1) 项目已在 /workspace/sellersprite-automation 时:
#        sudo bash setup_server.sh
#   2) 先解包部署包再部署:
#        sudo bash setup_server.sh /root/duratech-deploy.tar.gz
#   3) 自定义公网 IP (默认 116.62.43.110):
#        sudo SERVER_IP=1.2.3.4 bash setup_server.sh
#
# 执行完会输出访问地址，首次注册即管理员。
# ============================================================
set -euo pipefail

# ---------- 可配置参数 ----------
SERVER_IP="${SERVER_IP:-116.62.43.110}"
PROJECT_DIR="/workspace/sellersprite-automation"
WEB_DIR="$PROJECT_DIR/web"
VENV="$PROJECT_DIR/venv"
APP_PORT=58901
LOG_TAG="[DuraTech 部署]"

# 若第一个参数是 tar.gz，先解包到 /workspace
if [ $# -ge 1 ] && [[ "$1" == *.tar.gz || "$1" == *.tgz ]]; then
    PKG="$1"
    echo "$LOG_TAG 解包部署包: $PKG -> /workspace"
    tar -xzf "$PKG" -C /workspace
    shift
fi

# ---------- 前置检查 ----------
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ 请使用 root 运行: sudo bash $0" >&2
    exit 1
fi
if ! grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
    echo "⚠️  检测到非 Ubuntu 系统，脚本按 Ubuntu 22.04 编写，继续但可能失败"
fi
if [ ! -f "$WEB_DIR/pool_server.py" ]; then
    echo "❌ 找不到 $WEB_DIR/pool_server.py，请确认项目已就位" >&2
    exit 1
fi

echo "$LOG_TAG ========== 开始部署 =========="
echo "$LOG_TAG 服务器公网 IP : $SERVER_IP"
echo "$LOG_TAG 项目目录      : $PROJECT_DIR"

# ---------- 1. 安装系统依赖 ----------
echo "$LOG_TAG [1/9] 安装系统依赖 (nginx/python3/openssl/ufw) ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y nginx python3 python3-venv python3-pip curl git openssl ca-certificates ufw

# ---------- 2. 内存 <=2G 时划 2G swap ----------
MEM_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo)
if [ "$MEM_KB" -le 2097152 ]; then
    echo "$LOG_TAG [2/9] 检测到内存 <=2G，创建 2G swap 防止 OOM ..."
    if [ ! -f /swapfile ]; then
        fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
        chmod 600 /swapfile
        mkswap /swapfile
    fi
    swapon /swapfile || true
    grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
else
    echo "$LOG_TAG [2/9] 内存充足 (>2G)，跳过 swap"
fi

# ---------- 3. 创建必要目录 ----------
echo "$LOG_TAG [3/9] 创建运行目录 ..."
mkdir -p "$PROJECT_DIR"/{logs,output/weekly,output/archive,sessions}
mkdir -p /root/uploads /root/backups
chmod 700 /root/uploads

# ---------- 4. Python 虚拟环境 + 依赖 ----------
echo "$LOG_TAG [4/9] 创建 venv 并安装 Python 依赖 ..."
if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$WEB_DIR/requirements.txt" -q

# ---------- 5. 生成 SECRET_KEY ----------
echo "$LOG_TAG [5/9] 生成 SECRET_KEY ..."
SECRET_KEY=$("$VENV/bin/python" -c "import secrets;print(secrets.token_hex(32))")

# ---------- 6. Nginx (自签 HTTPS, 80->443 跳转) ----------
echo "$LOG_TAG [6/9] 配置 Nginx (自签证书, 监听 443) ..."
CERT_KEY=/etc/ssl/private/duratech.key
CERT_CRT=/etc/ssl/certs/duratech.crt
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CERT_KEY" -out "$CERT_CRT" -days 365 \
    -subj "/CN=$SERVER_IP" 2>/dev/null
chmod 600 "$CERT_KEY"

cat > /etc/nginx/sites-available/duratech <<NGINX
server {
    listen 80;
    server_name $SERVER_IP;
    # 明文 80 强制跳转到 HTTPS
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name $SERVER_IP;

    ssl_certificate     $CERT_CRT;
    ssl_certificate_key $CERT_KEY;
    ssl_protocols       TLSv1.2 TLSv1.3;

    client_max_body_size 20m;        # 允许上传较大的卖家精灵 Cookie/JSON
    proxy_read_timeout  120s;        # 需求池全量数据响应较慢
    proxy_send_timeout  120s;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/duratech /etc/nginx/sites-enabled/duratech
nginx -t
systemctl restart nginx
systemctl enable nginx

# ---------- 7. systemd 服务 ----------
echo "$LOG_TAG [7/9] 注册 systemd 服务 (poolboard) ..."
cat > /etc/systemd/system/poolboard.service <<UNIT
[Unit]
Description=DuraTech Demand Pool Board (Web)
After=network.target

[Service]
Type=simple
WorkingDirectory=$WEB_DIR
ExecStart=$VENV/bin/python -m waitress --host=127.0.0.1 --port=$APP_PORT --threads=8 pool_server:app
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=SECRET_KEY=$SECRET_KEY

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable poolboard
systemctl restart poolboard
sleep 4

# ---------- 8. 每日自动备份 (cron) ----------
echo "$LOG_TAG [8/9] 安装每日备份定时任务 ..."
CRON_LINE="0 3 * * * bash $PROJECT_DIR/deploy/backup.sh >> /root/backups/backup.log 2>&1"
( crontab -l 2>/dev/null | grep -v "deploy/backup.sh" ; echo "$CRON_LINE" ) | crontab -

# ---------- 9. 防火墙 ----------
echo "$LOG_TAG [9/9] 配置防火墙 ..."
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable || echo "$LOG_TAG (ufw 启用失败可忽略，请确保在阿里云控制台防火墙放行 80/443)"

# ---------- 健康检查 ----------
echo "$LOG_TAG ========== 健康检查 =========="
if curl -sk "https://127.0.0.1/api/health" | grep -q "ok"; then
    echo "$LOG_TAG ✅ 服务正常"
else
    echo "$LOG_TAG ⚠️  健康检查未通过，最近日志:"
    journalctl -u poolboard -n 20 --no-pager || true
fi

# ---------- 完成 ----------
echo ""
echo "============================================================"
echo " ✅ DuraTech 看板部署完成"
echo " 访问地址:  https://$SERVER_IP"
echo "   (自签证书，浏览器会提示不安全，点击「继续访问」即可)"
echo ""
echo " 首次使用:"
echo "   1. 浏览器打开上面地址"
echo "   2. 注册第一个账号 = 自动成为管理员"
echo "   3. 在需求池看板「上传 Cookie」粘贴卖家精灵 Cookie"
echo "   4. 系统自动开始采集，完成后勾选产品一键导入追踪看板"
echo ""
echo " 常用运维命令:"
echo "   查看日志 : journalctl -u poolboard -f"
echo "   重启服务 : systemctl restart poolboard"
echo "   数据备份 : bash $PROJECT_DIR/deploy/backup.sh"
echo "   备份位置 : /root/backups (保留 30 天)"
echo "============================================================"
