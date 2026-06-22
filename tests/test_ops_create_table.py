"""Tests for the v2 table-provisioning script (on-demand + TTL + idempotent)."""
import boto3

import models
from ops import create_v2_table


def test_creates_v2_table(aws_empty):
    create_v2_table.ensure_v2_table()
    assert models.ShortURLV2.exists()


def test_table_is_on_demand_not_provisioned(aws_empty):
    create_v2_table.ensure_v2_table()
    client = boto3.client("dynamodb", region_name="us-east-1")
    desc = client.describe_table(TableName=models.ShortURLV2.Meta.table_name)["Table"]
    assert desc["BillingModeSummary"]["BillingMode"] == "PAY_PER_REQUEST"


def test_ttl_enabled_on_expires_at(aws_empty):
    create_v2_table.ensure_v2_table()
    client = boto3.client("dynamodb", region_name="us-east-1")
    ttl = client.describe_time_to_live(
        TableName=models.ShortURLV2.Meta.table_name
    )["TimeToLiveDescription"]
    assert ttl["TimeToLiveStatus"] in ("ENABLED", "ENABLING")
    assert ttl["AttributeName"] == "expires_at"


def test_is_idempotent(aws_empty):
    create_v2_table.ensure_v2_table()
    create_v2_table.ensure_v2_table()  # must not raise
    assert models.ShortURLV2.exists()
