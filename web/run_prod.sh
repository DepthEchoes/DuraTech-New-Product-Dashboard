#!/usr/bin/env bash
# DuraTech 需求池看板在线版 - 生产启动脚本（waitress，单进程多线程）
# 用法: SECRET_KEY=xxx bash run_prod.sh
set -e
cd "$(dirname "$0")"

export SECRET_KEY="${SECRET_KEY:-$(python3 -c 'import secrets;print(secrets.token_hex(16))')}"

exec python3 -m waitress --host=127.0.0.1 --port=58901 --threads=8 pool_server:app
