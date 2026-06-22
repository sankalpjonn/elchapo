"""Integration tests for GET /<path> (redirect + copy-forward + metric)."""
from datetime import datetime, timedelta, timezone

import boto3
import pytz

import models


def _seed_v1(path, redirect="https://old.test/x", webhook=None, created=None):
    kwargs = dict(url=path, redirection_url=redirect)
    if webhook:
        kwargs["webhook"] = webhook
    if created:
        kwargs["created_at"] = created
    models.ShortURL(**kwargs).save()


def _seed_v2(path, redirect="https://new.test/x", webhook=None):
    kwargs = dict(url=path, redirection_url=redirect, expires_at=9999999999)
    if webhook:
        kwargs["webhook"] = webhook
    models.ShortURLV2(**kwargs).save()


def _age_metric_sample_count():
    cw = boto3.client("cloudwatch", region_name="us-east-1")
    stats = cw.get_metric_statistics(
        Namespace="Elchapo/staging", MetricName="ActiveLinkAgeDays",
        StartTime=datetime.now(timezone.utc) - timedelta(minutes=10),
        EndTime=datetime.now(timezone.utc) + timedelta(minutes=10),
        Period=3600, Statistics=["SampleCount"],
    )
    return sum(d["SampleCount"] for d in stats["Datapoints"])


def test_redirect_hit_in_v2_returns_302(client):
    _seed_v2("p-new")
    r = client.get("/p-new")
    assert r.status_code == 302
    assert r.headers["Location"] == "https://new.test/x"


def test_redirect_miss_returns_404(client):
    assert client.get("/nope-nothing-here").status_code == 404


def test_legacy_v1_hit_copies_forward_preserving_created_at(client):
    created = datetime(2024, 1, 1, tzinfo=pytz.UTC)
    _seed_v1("p-old", created=created)
    r = client.get("/p-old")
    assert r.status_code == 302
    v2 = models.ShortURLV2.get("p-old")
    assert v2.redirection_url == "https://old.test/x"
    assert v2.created_at == created          # preserved
    assert v2.expires_at is not None          # TTL stamped


def test_legacy_v1_hit_emits_one_age_metric_no_dimensions(client):
    _seed_v1("p-old", created=datetime(2024, 1, 1, tzinfo=pytz.UTC))
    client.get("/p-old")
    cw = boto3.client("cloudwatch", region_name="us-east-1")
    metrics = cw.list_metrics(Namespace="Elchapo/staging")["Metrics"]
    assert len(metrics) == 1
    assert metrics[0]["MetricName"] == "ActiveLinkAgeDays"
    assert metrics[0]["Dimensions"] == []
    assert _age_metric_sample_count() == 1


def test_second_hit_served_from_v2_no_second_copy_or_metric(client):
    _seed_v1("p-old", created=datetime(2024, 1, 1, tzinfo=pytz.UTC))
    client.get("/p-old")   # copy-forward + 1 metric
    client.get("/p-old")   # served from v2, no copy, no metric
    assert _age_metric_sample_count() == 1


def test_redirect_fires_webhook_with_path_param(client, webhook_calls):
    _seed_v2("p-hook", webhook="https://h.test/cb")
    client.get("/p-hook")
    assert "https://h.test/cb?path=p-hook" in webhook_calls
