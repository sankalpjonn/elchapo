"""
Benchmark a DIRECT boto3 put_item against DynamoDB -- the operation Goal 2 will
have Django run instead of POST /c through API Gateway.

What this proves, in one run, from a prod EC2 box using the api-access-user key:
  1. ACCESS   - the (newly-permissioned) key can actually write to the table.
  2. LATENCY  - real intra-region put_item latency (min/p50/p90/p95/p99/max),
                to compare against the ~96ms p99 the /c path costs today.
  3. THROUGHPUT/CONCURRENCY - sustained items/sec at a fixed worker count
                (default 17 = the p99 ConcurrentExecutions from the traffic
                baseline; max was 25), to compare against the per-endpoint RPS
                percentiles in elchapo_traffic_findings.

It writes throwaway rows (key prefix `bench-<run-id>-`) into the OLD STAGING v1
table, which is slated for deletion -- so no cleanup is required. The put mirrors
the Goal 2 write exactly: a CONDITIONAL put with attribute_not_exists(url) and a
representative v2-shaped payload (url, redirection_url, created_at, expires_at).

USAGE (run ON the prod box, with the api-access-user creds in the environment):

    # default chain picks up whatever creds the box/Django uses:
    python ops/bench_direct_put.py \
        --table staging-el-chapo-short-url-store --count 5000 --concurrency 17

    # or point at a named profile:
    AWS_PROFILE=whatever python ops/bench_direct_put.py --table ...

It prints the caller identity first so you can confirm you are benchmarking the
api-access-user key (not some admin), and fails fast with a clear message if the
key lacks PutItem (i.e. the IAM policy isn't applied yet).
"""
import argparse
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ----------------------------------------------------------------------------
# Pure helpers (unit-tested in tests/test_bench_direct_put.py)
# ----------------------------------------------------------------------------

PERCENTILES = (50, 90, 95, 99)


def percentile(values, p):
    """
    Nearest-rank percentile (same intent as CloudWatch extended stats): the
    smallest value at or below which p% of the data falls. Sorts defensively.
    """
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    if n == 1:
        return ordered[0]
    rank = math.ceil((p / 100.0) * n)
    idx = min(max(rank - 1, 0), n - 1)
    return ordered[idx]


def summarize(values):
    """min / p50 / p90 / p95 / p99 / max (+ count, avg) over a list of numbers."""
    if not values:
        return {"count": 0, "min": None, "max": None, "avg": None,
                "p50": None, "p90": None, "p95": None, "p99": None}
    out = {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": sum(values) / len(values),
    }
    for p in PERCENTILES:
        out["p%d" % p] = percentile(values, p)
    return out


def per_second_buckets(completion_offsets):
    """
    Bucket completion timestamps (seconds-from-start floats) into 1-second
    windows, INCLUDING idle seconds as 0, so the result is an items/sec time
    series we can percentile. e.g. [0.1,0.5,2.5] -> [2, 0, 1].
    """
    if not completion_offsets:
        return []
    last = int(max(completion_offsets))
    counts = [0] * (last + 1)
    for off in completion_offsets:
        counts[int(off)] += 1
    return counts


def build_item(run_id, index, ttl_epoch, created_iso):
    """
    A marshalled DynamoDB item mirroring the v2 short-url schema, sized like a
    real row. Keys are unique per (run_id, index) so the conditional put never
    collides.
    """
    return {
        "url": {"S": "bench-%s-%d" % (run_id, index)},
        "redirection_url": {
            "S": "https://example.com/landing/path/%s/%d?utm_source=bench&utm_campaign=elchapo"
                 % (run_id, index)
        },
        "created_at": {"S": created_iso},
        "expires_at": {"N": str(int(ttl_epoch))},
    }


def _fmt(stats, unit):
    if stats["count"] == 0:
        return "  (no samples)"
    return (
        "  min=%.2f  p50=%.2f  p90=%.2f  p95=%.2f  p99=%.2f  max=%.2f  (avg=%.2f, n=%d) %s"
        % (stats["min"], stats["p50"], stats["p90"], stats["p95"],
           stats["p99"], stats["max"], stats["avg"], stats["count"], unit)
    )


# ----------------------------------------------------------------------------
# Live benchmark (needs real AWS creds + network; not unit-tested)
# ----------------------------------------------------------------------------

def _make_client(region, pool_size):
    import boto3
    from botocore.config import Config
    # NO automatic retries: we want to MEASURE throttling, not hide it behind
    # silent backoff that inflates latency. In 'standard' mode max_attempts is
    # the TOTAL attempt count, so 1 == one try, zero retries. Pool must be >=
    # concurrency or workers serialize on connections and the test is a lie.
    cfg = Config(
        region_name=region,
        max_pool_connections=pool_size,
        retries={"max_attempts": 1, "mode": "standard"},
    )
    return boto3.client("dynamodb", config=cfg)


def _print_identity(region):
    import boto3
    sts = boto3.client("sts", region_name=region)
    ident = sts.get_caller_identity()
    print("Caller identity : %s" % ident["Arn"])
    print("Account         : %s" % ident["Account"])


def _ttl_epoch(days):
    return int(time.time()) + days * 86400


def _iso_now():
    # pynamodb UTCDateTimeAttribute format; only size matters for the benchmark
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000+0000", time.gmtime())


def run_benchmark(table, count, concurrency, region, ttl_days, run_id):
    from botocore.exceptions import ClientError

    client = _make_client(region, max(concurrency, 10))
    ttl_epoch = _ttl_epoch(ttl_days)
    created_iso = _iso_now()

    def one_put(index):
        item = build_item(run_id, index, ttl_epoch, created_iso)
        t0 = time.perf_counter()
        err = None
        try:
            client.put_item(
                TableName=table,
                Item=item,
                ConditionExpression="attribute_not_exists(#u)",
                ExpressionAttributeNames={"#u": "url"},
            )
        except ClientError as e:
            err = e.response["Error"]["Code"]
        except Exception as e:  # network etc.
            err = type(e).__name__
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return latency_ms, err

    # --- fail-fast canary: one put, surface AccessDenied clearly -------------
    print("Canary put      : verifying write access to %s ..." % table)
    canary_latency, canary_err = one_put(-1)
    if canary_err in ("AccessDeniedException", "AccessDenied"):
        print("\n  ACCESS DENIED on put_item. The api-access-user key cannot write to")
        print("  %s yet -- the scoped dynamodb:PutItem IAM policy (Goal 2, B2) is not" % table)
        print("  applied, or hasn't propagated. Fix that, then re-run.")
        return None
    if canary_err:
        print("  Canary put failed with: %s (aborting)" % canary_err)
        return None
    print("  OK (%.2f ms). Access confirmed.\n" % canary_latency)

    # --- the concurrent run --------------------------------------------------
    print("Running %d puts @ concurrency %d against %s ...\n" % (count, concurrency, table))
    latencies = []
    errors = {}
    completion_offsets = []

    wall_t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(one_put, i) for i in range(count)]
        for fut in as_completed(futures):
            latency_ms, err = fut.result()
            completion_offsets.append(time.perf_counter() - wall_t0)
            if err:
                errors[err] = errors.get(err, 0) + 1
            else:
                latencies.append(latency_ms)
    wall = time.perf_counter() - wall_t0

    return {
        "latencies": latencies,
        "errors": errors,
        "completion_offsets": completion_offsets,
        "wall": wall,
        "count": count,
        "concurrency": concurrency,
    }


def report(result):
    lat = summarize(result["latencies"])
    tput = summarize(per_second_buckets(result["completion_offsets"]))
    ok = len(result["latencies"])
    wall = result["wall"]

    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print("requested        : %d puts @ concurrency %d"
          % (result["count"], result["concurrency"]))
    print("succeeded        : %d" % ok)
    if result["errors"]:
        print("errors           : %s" % result["errors"])
    print("wall-clock       : %.2f s" % wall)
    print("overall rate     : %.1f puts/sec" % (ok / wall if wall else 0))
    print()
    print("per-put latency (ms):")
    print(_fmt(lat, "ms"))
    print()
    print("throughput per 1s window (puts/sec) -- compare vs the POST /c RPS percentiles:")
    print(_fmt(tput, "puts/sec"))
    print("=" * 70)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", default="staging-el-chapo-short-url-store",
                    help="DynamoDB table to write throwaway rows into "
                         "(default: the old staging v1 table, slated for deletion)")
    ap.add_argument("--count", type=int, default=5000, help="number of puts (default 5000)")
    ap.add_argument("--concurrency", type=int, default=17,
                    help="worker threads = in-flight puts (default 17 = p99 "
                         "ConcurrentExecutions from the baseline; max was 25)")
    ap.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    ap.add_argument("--ttl-days", type=int, default=180,
                    help="expires_at = now + ttl-days (epoch seconds); for payload "
                         "realism only -- the v1 table has no TTL enabled")
    ap.add_argument("--run-id", default=str(int(time.time())),
                    help="suffix for bench- keys (default: epoch seconds)")
    args = ap.parse_args()

    print("=" * 70)
    print("elchapo direct put_item benchmark")
    print("=" * 70)
    print("region          : %s" % args.region)
    print("table           : %s" % args.table)
    _print_identity(args.region)
    print()

    result = run_benchmark(args.table, args.count, args.concurrency,
                           args.region, args.ttl_days, args.run_id)
    if result is None:
        sys.exit(1)
    report(result)


if __name__ == "__main__":
    main()
