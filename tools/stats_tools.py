"""Statistical computation tools — deterministic, trustworthy results.

These produce the numeric KPIs and distributions that AI narrative
is built on. Numbers from these tools are authoritative.
"""

from typing import Any

import numpy as np


def calculate_stats(data: list[float | int], metrics: list[str] | None = None) -> dict:
    """Calculate descriptive statistics for a numeric dataset.

    Args:
        data: List of numeric values (e.g. student scores).
        metrics: Which metrics to compute. Defaults to all.
            Supported: mean, median, stddev, min, max, percentiles, distribution.

    Returns:
        Dictionary of computed metric results.
    """
    if not data:
        return {"error": "Empty data list"}

    arr = np.array(data, dtype=float)
    all_metrics = metrics or ["mean", "median", "stddev", "min", "max", "percentiles", "distribution"]

    result: dict[str, Any] = {"count": len(data)}

    if "mean" in all_metrics:
        result["mean"] = round(float(np.mean(arr)), 2)
    if "median" in all_metrics:
        result["median"] = round(float(np.median(arr)), 2)
    if "stddev" in all_metrics:
        result["stddev"] = round(float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0, 2)
    if "min" in all_metrics:
        result["min"] = round(float(np.min(arr)), 2)
    if "max" in all_metrics:
        result["max"] = round(float(np.max(arr)), 2)
    if "percentiles" in all_metrics:
        result["percentiles"] = {
            "p25": round(float(np.percentile(arr, 25)), 2),
            "p50": round(float(np.percentile(arr, 50)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
            "p90": round(float(np.percentile(arr, 90)), 2),
        }
    if "distribution" in all_metrics:
        bins = [0, 40, 50, 60, 70, 80, 90, 100]
        labels = ["0-39", "40-49", "50-59", "60-69", "70-79", "80-89", "90-100"]
        counts, _ = np.histogram(arr, bins=bins)
        result["distribution"] = {
            "labels": labels,
            "counts": [int(c) for c in counts],
        }

    return result


def compare_performance(
    group_a: list[float | int],
    group_b: list[float | int],
    metrics: list[str] | None = None,
) -> dict:
    """Compare performance between two groups of scores.

    Args:
        group_a: First group of numeric scores.
        group_b: Second group of numeric scores.
        metrics: Which metrics to compare. Defaults to ["mean", "median", "stddev"].

    Returns:
        Dictionary with stats for each group, differences, and a summary.
    """
    if not group_a or not group_b:
        return {"error": "Both groups must be non-empty"}

    compare_metrics = metrics or ["mean", "median", "stddev"]

    stats_a = calculate_stats(group_a, compare_metrics)
    stats_b = calculate_stats(group_b, compare_metrics)

    diff: dict[str, float] = {}
    for key in compare_metrics:
        if key in stats_a and key in stats_b and isinstance(stats_a[key], (int, float)):
            diff[key] = round(stats_a[key] - stats_b[key], 2)

    return {
        "group_a": stats_a,
        "group_b": stats_b,
        "difference": diff,
        "summary": {
            "group_a_count": stats_a.get("count", 0),
            "group_b_count": stats_b.get("count", 0),
        },
    }
