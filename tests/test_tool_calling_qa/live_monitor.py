"""Real-time test monitor — writes JSON + serves HTML dashboard on localhost.

Supports both single-model and multi-model comparison modes.

Usage:
    monitor = LiveMonitor.get()
    monitor.start_session("D9: Execution Fidelity", "glm-4.7", case_list)
    monitor.mark_running("pwe-01")
    monitor.record("pwe-01", passed=True, verdict="OK", ...)

    # Multi-model:
    monitor.start_session("D9", "multi", case_list, models=["glm-4.7", "qwen3"])
    monitor.mark_running("pwe-01", model="glm-4.7")
    monitor.record("pwe-01", passed=True, verdict="OK", ..., model="glm-4.7")

Dashboard: http://localhost:8888
Standalone server: python tests/test_tool_calling_qa/serve_monitor.py
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

_MONITOR_DIR = Path(__file__).parent / "_live_output"
_JSON_PATH = _MONITOR_DIR / "results.json"
_DEFAULT_PORT = 8888


class _NoCacheHandler(SimpleHTTPRequestHandler):
    """Serve files with no-cache headers, CORS, and UTF-8."""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def guess_type(self, path):
        t = super().guess_type(path)
        if isinstance(t, str) and t in ("text/html", "application/json"):
            return t + "; charset=utf-8"
        return t

    def log_message(self, format, *args):
        pass  # Silence per-request logs


def _empty_result() -> dict:
    return {
        "status": "pending",
        "verdict": "",
        "latency_ms": 0,
        "tool_calls": [],
        "output_text": "",
        "error": "",
        "flags": {},
        "timestamp": None,
    }


class LiveMonitor:
    """Singleton: writes test results to JSON and optionally serves dashboard."""

    _instance: LiveMonitor | None = None

    @classmethod
    def get(cls) -> LiveMonitor:
        if cls._instance is None:
            cls._instance = LiveMonitor()
        return cls._instance

    def __init__(self):
        self._state: dict[str, Any] = {"session": {}, "cases": []}
        self._server: HTTPServer | None = None
        self._lock = threading.Lock()
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start_session(
        self,
        suite: str,
        model: str,
        case_list: list[tuple],
        port: int = _DEFAULT_PORT,
        models: list[str] | None = None,
    ):
        """Initialize state, copy HTML, start HTTP server.

        Args:
            models: If provided, enables multi-model mode. Each case gets a
                    ``models`` dict keyed by model label.
        """
        _MONITOR_DIR.mkdir(exist_ok=True)

        # Copy dashboard HTML -> _live_output/index.html
        src = Path(__file__).parent / "monitor_dashboard.html"
        dst = _MONITOR_DIR / "index.html"
        if src.exists():
            shutil.copy2(src, dst)

        multi = models is not None and len(models) > 1
        self._state = {
            "session": {
                "suite": suite,
                "model": model,
                "models": models or [model],
                "mode": "multi" if multi else "single",
                "start_time": time.time(),
                "end_time": None,
                "status": "running",
                "total_cases": len(case_list),
            },
            "cases": [
                {
                    "case_id": c[0],
                    "sub_dim": c[1] if len(c) > 1 else "",
                    "description": c[2] if len(c) > 2 else "",
                    # Top-level: single-model compat
                    **_empty_result(),
                    # Multi-model dict (always present, may be empty)
                    "models": (
                        {m: _empty_result() for m in models}
                        if multi else {}
                    ),
                }
                for c in case_list
            ],
        }
        self._flush()
        self._start_http(port)
        self._started = True

    def mark_running(self, case_id: str, model: str | None = None):
        with self._lock:
            for c in self._state["cases"]:
                if c["case_id"] == case_id:
                    if model and model in c.get("models", {}):
                        c["models"][model]["status"] = "running"
                        c["models"][model]["timestamp"] = time.time()
                    else:
                        c["status"] = "running"
                        c["timestamp"] = time.time()
                    break
            self._flush()

    def record(
        self,
        case_id: str,
        passed: bool,
        verdict: str,
        latency_ms: float = 0,
        tool_calls: list | None = None,
        output_text: str = "",
        error: str = "",
        flags: dict | None = None,
        model: str | None = None,
    ):
        with self._lock:
            found = False
            for c in self._state["cases"]:
                if c["case_id"] == case_id:
                    entry = {
                        "status": "passed" if passed else "failed",
                        "verdict": verdict,
                        "latency_ms": latency_ms,
                        "tool_calls": tool_calls or [],
                        "output_text": (output_text[:500] if output_text else ""),
                        "error": error,
                        "flags": flags or {},
                        "timestamp": time.time(),
                    }
                    if model and model in c.get("models", {}):
                        # Multi-model: write into models dict
                        c["models"][model] = entry
                    else:
                        # Single-model: write top-level
                        c.update(entry)
                    found = True
                    break
            if found:
                self._flush()

    def end_session(self):
        with self._lock:
            if self._state.get("session"):
                self._state["session"]["end_time"] = time.time()
                self._state["session"]["status"] = "completed"
                self._flush()

    # ── internal ──────────────────────────────────────────────

    def _flush(self):
        tmp = _JSON_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)
        try:
            os.replace(str(tmp), str(_JSON_PATH))
        except OSError:
            shutil.move(str(tmp), str(_JSON_PATH))

    def _start_http(self, port: int):
        if self._server:
            return
        try:
            handler = partial(_NoCacheHandler, directory=str(_MONITOR_DIR))
            self._server = HTTPServer(("0.0.0.0", port), handler)
            t = threading.Thread(target=self._server.serve_forever, daemon=True)
            t.start()
            print(f"\n  >>> Live Monitor: http://localhost:{port}")
            print(f"  >>> Results JSON: {_JSON_PATH}\n")
        except OSError as e:
            print(f"\n  !!! Could not start monitor on port {port}: {e}")
            print(f"  !!! JSON still at: {_JSON_PATH}\n")

    def stop_server(self):
        if self._server:
            self._server.shutdown()
            self._server = None
