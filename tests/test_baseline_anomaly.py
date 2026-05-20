"""Baseline-aware anomaly detection tests."""

from anomaly_detection import (
    effective_threshold,
    is_metric_above_threshold,
)


def test_effective_threshold_uses_max_of_static_and_baseline() -> None:
    assert effective_threshold(80, 70, margin=1.15, use_baseline=True) == 80.5
    assert effective_threshold(80, 50, margin=1.15, use_baseline=True) == 80


def test_baseline_suppresses_below_margin() -> None:
    # Static 80 would fire; baseline p95 70 * 1.15 = 80.5 — value 81 fires, 80 does not
    assert not is_metric_above_threshold(79, 80, 70, margin=1.15, use_baseline=True)
    assert is_metric_above_threshold(81, 80, 70, margin=1.15, use_baseline=True)


def test_without_baseline_uses_static_only() -> None:
    assert is_metric_above_threshold(81, 80, 70, use_baseline=False)
    assert not is_metric_above_threshold(79, 80, 70, use_baseline=False)
