"""
Provision the v2 short-url table for the current ENVIRONMENT.

Creates `<env>-el-chapo-short-url-store-v2` as an ON-DEMAND (PAY_PER_REQUEST)
table and enables native TTL on the `expires_at` attribute. Idempotent: safe to
re-run; it no-ops if the table / TTL already exist.

Usage (env selects staging vs production):
    ENVIRONMENT=staging    python ops/create_v2_table.py
    ENVIRONMENT=production python ops/create_v2_table.py
"""
import os
import sys

# Make repo-root modules importable when run as `python ops/create_v2_table.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3

from constants import AWS_REGION, ENV
from models import ShortURLV2

TTL_ATTRIBUTE = "expires_at"


def _enable_ttl(table_name):
    client = boto3.client("dynamodb", region_name=AWS_REGION)
    status = client.describe_time_to_live(
        TableName=table_name
    )["TimeToLiveDescription"]["TimeToLiveStatus"]
    if status in ("ENABLED", "ENABLING"):
        return False
    client.update_time_to_live(
        TableName=table_name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE},
    )
    return True


def ensure_v2_table():
    """Create the on-demand v2 table (if missing) and enable TTL. Idempotent."""
    table_name = ShortURLV2.Meta.table_name
    created = False
    if not ShortURLV2.exists():
        ShortURLV2.create_table(billing_mode="PAY_PER_REQUEST", wait=True)
        created = True
    ttl_set = _enable_ttl(table_name)
    return {"table": table_name, "created": created, "ttl_set": ttl_set}


if __name__ == "__main__":
    print("Ensuring v2 table for ENVIRONMENT=%s ..." % ENV)
    result = ensure_v2_table()
    print(
        "Done: %s | created=%s | ttl_enabled_now=%s | billing=PAY_PER_REQUEST (on-demand)"
        % (result["table"], result["created"], result["ttl_set"])
    )
