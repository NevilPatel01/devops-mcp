"""Baseline-aware anomaly helpers (pure functions for tests)."""

from __future__ import annotations


def effective_threshold(
    static_threshold: float,
    baseline_p95: float | None,
    *,
    margin: float = 1.15,
    use_baseline: bool = True,
) -> float:
    """Return the threshold value that must be exceeded to count as an anomaly."""
    if not use_baseline or baseline_p95 is None:
        return static_threshold
    return max(static_threshold, baseline_p95 * margin)


def is_metric_above_threshold(
    value: float | None,
    static_threshold: float,
    baseline_p95: float | None,
    *,
    margin: float = 1.15,
    use_baseline: bool = True,
) -> bool:
    if value is None:
        return False
    return value > effective_threshold(
        static_threshold, baseline_p95, margin=margin, use_baseline=use_baseline
    )


def anomaly_signature(reason: str, service_name: str | None) -> str:
    return f"{reason}|{service_name or ''}"


def compute_fatigue_score(false_positive_count: int, true_positive_count: int) -> float:
    """0 = trusted alerts, 100 = high false-alarm rate."""
    total = false_positive_count + true_positive_count
    if total <= 0:
        return 0.0
    return round(min(100.0, 100.0 * false_positive_count / total), 2)
