"""
DuraTech 需求池看板在线版 - 采集任务管理器
后台 daemon 线程顺序执行: 采集新品 → 采集爆品 → 周环比去重 → 重建需求池看板
全局状态机: state / step / progress / logs / error / result
import_lock: 串行化对 dashboard_builder 的调用（一键导入），避免并发文件竞争
"""
import io
import sys
import threading
import traceback
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
WEB_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(WEB_DIR))

import collector
import weekly_diff
import pool_builder
import dashboard_builder

POOL_HTML = WEB_DIR / "pool.html"
TRACKING_HTML = WEB_DIR / "board.html"
LOG_LIMIT = 4000


class JobManager:
    def __init__(self):
        self._lock = threading.Lock()          # 控制任务启动/状态写入
        self.import_lock = threading.Lock()    # 串行化 dashboard_builder 调用
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
        """启动采集任务；已在运行返回 False"""
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.step = "prepare"
            self.progress = 0
            self.logs = ""
            self.error = ""
            self.result = {}
            self._thread = threading.Thread(
                target=self._run, args=(max_pages,), daemon=True)
            self._thread.start()
            return True

    def snapshot(self):
        """返回状态快照（线程安全读取）"""
        with self._lock:
            return {
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

    def _run(self, max_pages):
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

            # 汇总结果
            result = {}
            for ct in ("new", "hot"):
                pool = pool_builder.load_pool(ct)
                if pool:
                    result[ct] = len(pool.get("products", []))
            self._log("采集完成: 新品 %s 条, 爆品 %s 条"
                      % (result.get("new", 0), result.get("hot", 0)))
            self._set(state="done", result=result)
        except Exception as e:
            err = "".join(traceback.format_exception_only(type(e), e)).strip()
            self._log(f"[ERROR] {err}\n{buf.getvalue()[-1500:]}")
            self._set(state="error", error=err)
        finally:
            buf.close()


# 全局单例
job_manager = JobManager()
