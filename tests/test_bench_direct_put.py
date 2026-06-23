"""
Tests for the pure helpers in the direct-put benchmark harness
(ops/bench_direct_put.py). The concurrent boto3 part is exercised live against
the old staging table from the prod box; only the deterministic math/builders
are unit-tested here.
"""
from ops import bench_direct_put as bench


# --- percentile (nearest-rank) ---------------------------------------------

def test_percentile_nearest_rank_basic():
    values = list(range(1, 11))  # 1..10
    assert bench.percentile(values, 50) == 5
    assert bench.percentile(values, 90) == 9
    assert bench.percentile(values, 95) == 10
    assert bench.percentile(values, 99) == 10


def test_percentile_unsorted_input_is_sorted_first():
    assert bench.percentile([9, 1, 5, 3, 7], 50) == 5


def test_percentile_single_value():
    assert bench.percentile([42.0], 99) == 42.0


# --- summarize -------------------------------------------------------------

def test_summarize_reports_all_requested_stats():
    values = [float(i) for i in range(1, 101)]  # 1..100
    s = bench.summarize(values)
    assert s["min"] == 1
    assert s["max"] == 100
    assert s["p50"] == 50
    assert s["p90"] == 90
    assert s["p95"] == 95
    assert s["p99"] == 99
    assert s["count"] == 100
    # the keys callers render, in case the shape changes
    for k in ("min", "p50", "p90", "p95", "p99", "max"):
        assert k in s


def test_summarize_empty_is_safe():
    s = bench.summarize([])
    assert s["count"] == 0
    assert s["min"] is None and s["max"] is None


# --- per-second throughput bucketing ---------------------------------------

def test_per_second_buckets_counts_completions_per_window():
    offsets = [0.1, 0.5, 0.9, 1.2, 1.8]
    assert bench.per_second_buckets(offsets) == [3, 2]


def test_per_second_buckets_fills_idle_seconds_with_zero():
    # nothing completed in the 2nd second -> a 0 bucket must appear
    offsets = [0.1, 0.2, 2.5]
    assert bench.per_second_buckets(offsets) == [2, 0, 1]


def test_per_second_buckets_empty():
    assert bench.per_second_buckets([]) == []


# --- item builder ----------------------------------------------------------

def test_build_item_is_marshalled_and_unique():
    a = bench.build_item("run1", 0, ttl_epoch=1700000000, created_iso="2026-06-22T00:00:00+0000")
    b = bench.build_item("run1", 1, ttl_epoch=1700000000, created_iso="2026-06-22T00:00:00+0000")
    assert a["url"]["S"] != b["url"]["S"]
    assert a["url"]["S"].startswith("bench-run1-")
    # mirrors the v2 schema so the payload size is representative
    assert a["redirection_url"]["S"]
    assert a["created_at"]["S"] == "2026-06-22T00:00:00+0000"
    # TTL must be epoch SECONDS, sent as a DynamoDB Number
    assert a["expires_at"]["N"] == "1700000000"
