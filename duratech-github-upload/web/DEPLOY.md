# DuraTech 需求池看板在线版 · 部署指南

> 功能：账号密码登录 → 上传卖家精灵 Cookie → 自动采集 → 勾选产品一键导入产品追踪看板
> 部署目标：云服务器公网 + 域名 + HTTPS

---

## 一、架构

```
浏览器（需求池看板 web 版）
   │  HTTPS
   ▼
Nginx（80/443 + 证书）
   │  反向代理
   ▼
waitress（127.0.0.1:58901，单进程 8 线程）
   └── pool_server.py（Flask）
         ├── 账号系统（users/sessions 表，SQLite board.db）
         ├── Cookie 上传 → 自动触发采集任务（后台线程）
         ├── 采集状态轮询
         ├── 需求池数据 / 一键导入
         └── 追踪看板页 /tracking
```

文件清单（`web/` 目录）：
| 文件 | 作用 |
|---|---|
| `pool_server.py` | Flask 主入口（全部路由） |
| `auth.py` | 注册/登录/token/权限装饰器 |
| `tasks.py` | 采集任务线程管理器 + 全局状态 |
| `db.py` | SQLite 数据层（products/progress/users/sessions + 池读取/导入辅助） |
| `run_prod.sh` | waitress 生产启动脚本 |
| `requirements.txt` | Python 依赖 |
| `board.service` | systemd 单元示例 |
| `../deploy/nginx.conf` | Nginx 反代配置示例 |
| `../deploy/backup.sh` | 每日备份脚本 |

> **重要**：生产必须「单进程 + 多线程」（waitress `--threads=8`），采集任务状态保存在进程内存中，多 worker 会互相看不到任务状态。

---

## 二、服务器准备

1. 云服务器（Ubuntu 22.04+），开放 **80/443** 端口
2. 域名解析到服务器 IP（推荐；也可先用 IP 访问）
3. 安装 Python 3.11 + nginx

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv nginx
```

---

## 三、部署步骤

### 1. 上传代码
把整个项目上传到服务器，例如 `/workspace/sellersprite-automation`（与本地路径保持一致最简单，
`config.py` 里的 `OUTPUT_DIR`/`WORKSPACE_OUTPUT` 均为绝对路径）。

### 2. 安装依赖
```bash
cd /workspace/sellersprite-automation/web
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 初始化验证（开发模式）
```bash
SECRET_KEY=dev_secret python3 pool_server.py
# 浏览器访问 http://服务器IP:58901/login → 注册第一个账号（自动成为管理员）
```

### 4. systemd 常驻运行
```bash
sudo cp board.service /etc/systemd/system/poolboard.service
# 编辑 board.service：修改 SECRET_KEY 为随机字符串、venv/python 路径
sudo systemctl daemon-reload
sudo systemctl enable --now poolboard
sudo systemctl status poolboard
```

### 5. Nginx 反代 + HTTPS
```bash
sudo cp ../deploy/nginx.conf /etc/nginx/sites-available/poolboard
sudo ln -s /etc/nginx/sites-available/poolboard /etc/nginx/sites-enabled/
# 修改 server_name 为你的域名
sudo nginx -t && sudo systemctl reload nginx

# 免费 HTTPS
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 6. 每日备份（cron）
```bash
sudo crontab -e
# 添加一行：
0 3 * * * bash /workspace/sellersprite-automation/deploy/backup.sh >> /var/log/duratech_backup.log 2>&1
```

---

## 四、首次使用流程

1. 打开 `https://your-domain.com` → 自动跳转登录页 → **注册第一个账号（自动成为管理员）**
2. 登录后进入需求池看板，顶部「🍪 卖家精灵 Cookie」卡片：
   - 选择 EditThisCookie 导出的 JSON 文件，或把 JSON 文本粘贴到输入框
   - 点「📤 上传并开始采集」→ **自动开始采集**，页面实时显示进度（采集新品→爆品→去重→重建看板）
3. 采集完成后数据自动刷新；在表格里勾选产品 → 点「📤 转入追踪看板」
   - 浏览器直接调用导入接口，提示「新增 X / 跳过 Y」，**无需再人工转交 JSON 文件**
4. 打开 `https://your-domain.com/tracking` 查看导入后的产品追踪看板

---

## 五、账号管理（管理员）

- 普通用户：登录后可用上传 Cookie、采集、导入等全部功能
- 管理员：额外可用用户管理接口
  - `GET /api/users`、`POST /api/users`（建号）、`DELETE /api/users/<id>`（删号）

---

## 六、接口一览

| 方法/路径 | 说明 |
|---|---|
| POST `/api/auth/register` | 注册（首个用户=admin） |
| POST `/api/auth/login` | 登录，返回 token |
| POST `/api/auth/logout` / GET `/api/auth/me` | 登出 / 当前用户 |
| GET/POST `/api/users`、DELETE `/api/users/<id>` | 用户管理（admin） |
| POST `/api/cookie` | 上传 Cookie（file 或 cookie_text），自动触发采集 |
| GET `/api/collection/status` | 采集状态轮询 |
| POST `/api/collection/start` | 手动触发采集 |
| GET `/api/pool` | 需求池数据 |
| POST `/api/pool/import` | 勾选产品一键导入追踪看板 |
| GET `/`、`/tracking`、`/login` | 页面 |

---

## 七、维护

| 操作 | 命令 |
|---|---|
| 查看日志 | `sudo journalctl -u poolboard -f` |
| 重启服务 | `sudo systemctl restart poolboard` |
| 备份 | `bash /workspace/sellersprite-automation/deploy/backup.sh`（自动保留 30 天） |
| 升级代码 | 覆盖 `web/` 与 `scripts/` 后重启服务 |

## 八、安全注意

- Cookie 是卖家精灵登录凭证：**仅登录用户可上传**，落盘权限 600，日志不回显
- 首次注册账号后请尽快在 `/api/users` 创建团队账号，避免公共注册（如需关闭注册，可改 `pool_server.py`）
- 必须启用 HTTPS（token 与 Cookie 走加密传输）
- `SECRET_KEY` 用随机字符串，不要用默认值
