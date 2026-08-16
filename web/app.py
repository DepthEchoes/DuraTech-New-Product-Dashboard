"""
DuraTech 产品追踪看板 - Web 版后端
提供：
  GET  /           看板页面
  GET  /api/board  产品+进度数据
  POST /api/progress  批量保存进度/备注/排序
  POST /api/import   上传卖家精灵 JSON 刷新产品池
  GET  /api/stats   统计概览
"""
import sys
from pathlib import Path
from flask import Flask, request, jsonify, Response

sys.path.insert(0, str(Path(__file__).parent))
from db import (init_db, refresh_products, load_progress_backup,
                get_board, save_progress, get_stats)

app = Flask(__name__)

# ===== 启动时初始化 =====
init_db()
refresh_products()
load_progress_backup()


@app.route("/api/board")
def api_board():
    products = get_board()
    return jsonify({"products": products, "stats": get_stats()})


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@app.route("/api/progress", methods=["POST"])
def api_progress():
    data = request.get_json(force=True, silent=True) or {}
    updates = data.get("updates", [])
    if not isinstance(updates, list):
        return jsonify({"ok": False, "error": "updates 必须为数组"}), 400
    n = save_progress(updates)
    return jsonify({"ok": True, "saved": n})


@app.route("/api/import", methods=["POST"])
def api_import():
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "未收到文件"}), 400
    # 保存到 uploads 目录后刷新
    ts = Path("/root/uploads")
    ts.mkdir(parents=True, exist_ok=True)
    dest = ts / f"import_{int(__import__('time').time())}.json"
    file.save(str(dest))
    n = refresh_products()
    return jsonify({"ok": True, "products": n})


@app.route("/")
def index():
    # 看板 HTML 由 dashboard_builder 在 web 模式下生成（输出到 web 目录，不覆盖本地版）
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import dashboard_builder
    out = dashboard_builder.build_dashboard(
        output_path=Path(__file__).parent / "board.html", web_mode=True)
    return Response(Path(out).read_text(encoding="utf-8"), mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=58901, debug=False)
