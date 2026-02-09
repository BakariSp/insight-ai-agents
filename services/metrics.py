"""Metrics aggregation for native runtime.

Step 2+: collect per-tool and per-turn metrics in memory so guardrail tests
can assert tool-call counts, success rate, and latency bounds.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


class MetricsCollector:
    """Thread-safe in-memory metrics collector."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tool_latencies: dict[str, list[float]] = defaultdict(list)
        self._tool_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._turn_stats: dict[str, dict] = {}

    def record_tool_call(
        self,
        *,
        tool_name: str,
        status: str,
        latency_ms: float,
        turn_id: str = "",
        conversation_id: str = "",
    ) -> None:
        with self._lock:
            self._tool_latencies[tool_name].append(float(latency_ms))
            self._tool_status[tool_name][status] += 1

            if turn_id:
                turn = self._turn_stats.setdefault(
                    turn_id,
                    {
                        "turn_id": turn_id,
                        "conversation_id": conversation_id,
                        "tool_call_count": 0,
                        "tool_error_count": 0,
                        "total_latency_ms": 0.0,
                    },
                )
                turn["tool_call_count"] += 1
                if status != "ok":
                    turn["tool_error_count"] += 1
                turn["total_latency_ms"] += float(latency_ms)

    def get_turn_summary(self, turn_id: str) -> dict:
        with self._lock:
            return dict(self._turn_stats.get(turn_id, {}))

    def snapshot(self) -> dict:
        with self._lock:
            tool_metrics = {}
            for tool, latencies in self._tool_latencies.items():
                status_map = self._tool_status.get(tool, {})
                total = sum(status_map.values())
                ok_count = status_map.get("ok", 0)
                tool_metrics[tool] = {
                    "count": total,
                    "success_rate": (ok_count / total) if total else 0.0,
                    "latency_p50_ms": round(_percentile(latencies, 0.5), 2),
                    "latency_p95_ms": round(_percentile(latencies, 0.95), 2),
                    "status_breakdown": dict(status_map),
                }

            return {
                "tools": tool_metrics,
                "turns": list(self._turn_stats.values()),
            }

    def reset(self) -> None:
        with self._lock:
            self._tool_latencies.clear()
            self._tool_status.clear()
            self._turn_stats.clear()


_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _metrics_collector

