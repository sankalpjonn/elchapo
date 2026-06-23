"""
Prove DynamoDB TTL is being honored on the v2 table for the current ENVIRONMENT.

TTL is "configured" (describe-time-to-live ENABLED on expires_at) vs "honored"
(actually deleting expired items). DynamoDB deletes expired items in the
background, up to ~48h after expiry, and SILENTLY ignores any item whose
expires_at isn't a Number in epoch SECONDS -- so we prove it empirically:

    # 1. write an already-expired canary (needs PutItem creds):
    ENVIRONMENT=staging python ops/check_ttl.py --seed
    # 2. later (minutes to ~48h), check it was reaped + the deletion metric:
    ENVIRONMENT=staging python ops/check_ttl.py
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from constants import AWS_REGION, ENV
from models import ShortURLV2
from utils import get_now, to_epoch_seconds

CANARY_KEY = "ttl-canary"


def build_canary(now):
    """An already-expired (expires_at = 1h ago) sentinel item."""
    return ShortURLV2(
        url=CANARY_KEY,
        redirection_url="https://example.test/ttl-canary",
        expires_at=to_epoch_seconds(now) - 3600,
    )


def summarize_ttl_metric(datapoints):
    return sum(d.get("Sum", 0) for d in datapoints)


def deleted_count(table_name, hours=48):
    cw = boto3.client("cloudwatch", region_name=AWS_REGION)
    resp = cw.get_metric_statistics(
        Namespace="AWS/DynamoDB", MetricName="TimeToLiveDeletedItemCount",
        Dimensions=[{"Name": "TableName", "Value": table_name}],
        StartTime=datetime.now(timezone.utc) - timedelta(hours=hours),
        EndTime=datetime.now(timezone.utc),
        Period=86400, Statistics=["Sum"],
    )
    return summarize_ttl_metric(resp.get("Datapoints", []))


def canary_present():
    try:
        ShortURLV2.get(CANARY_KEY)
        return True
    except ShortURLV2.DoesNotExist:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", action="store_true",
                    help="write an already-expired canary item (needs PutItem)")
    args = ap.parse_args()
    table = ShortURLV2.Meta.table_name

    if args.seed:
        build_canary(get_now()).save()
        print("Seeded expired canary '%s' into %s (expires_at = 1h in the past)."
              % (CANARY_KEY, table))
        print("DynamoDB TTL deletion can lag up to ~48h; re-run without --seed to check.")
        return

    present = canary_present()
    deleted = deleted_count(table)
    print("ENV=%s  table=%s" % (ENV, table))
    print("canary '%s' still present: %s" % (CANARY_KEY, present))
    print("TimeToLiveDeletedItemCount (last 48h, Sum): %s" % deleted)
    if not present and deleted >= 1:
        print("=> TTL IS being honored (canary was reaped).")
    elif present:
        print("=> canary still present; deletion may not have run yet (up to ~48h lag).")
    else:
        print("=> no canary found; seed one with --seed first.")


if __name__ == "__main__":
    main()
