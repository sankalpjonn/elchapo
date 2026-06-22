"""
End-to-end smoke test for a DEPLOYED elchapo stack (staging first, then prod).

Exercises the full matrix the unit tests cover, but against the real
API Gateway -> Lambda -> DynamoDB/CloudWatch path, so it also proves the
deploy, IAM grants, and TTL config are correct.

HTTP-only cases need just --base-url + --secret. The copy-forward / TTL /
metric cases need --verify-aws (boto3 creds for the same account) and run
against the tables for the current ENVIRONMENT, so set it to match the URL:

    ENVIRONMENT=staging python ops/smoke_test.py \
        --base-url https://slink.delight.chat --secret <staging-secret> --verify-aws

Exits non-zero if any case fails. Cleans up the rows it creates.
"""
import argparse
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, (" :: " + detail) if detail else ""))


def run(base_url, secret, verify_aws):
    base = base_url.rstrip("/")
    suffix = uuid.uuid4().hex[:8]
    new_path = "smoke-%s" % suffix
    legacy_path = "smoke-legacy-%s" % suffix
    dest = "https://example.test/%s" % suffix

    def post(path, sk=secret, redirect=dest, webhook=None):
        return requests.post(base + "/c", json={
            "path": path, "redirect_url": redirect,
            "webhook": webhook, "secret_key": sk,
        }, timeout=15)

    # ---- HTTP-only cases ----
    r = requests.get(base + "/", timeout=15)
    check("health GET / -> 200", r.status_code == 200, "got %s" % r.status_code)

    r = post(new_path)
    check("insert new -> 200", r.status_code == 200, "got %s" % r.status_code)

    r = post(new_path, redirect="https://other.test")
    check("duplicate -> 409", r.status_code == 409, "got %s" % r.status_code)

    r = post("smoke-sec-%s" % suffix, sk="WRONG-SECRET")
    check("bad secret -> 403", r.status_code == 403, "got %s" % r.status_code)

    r = requests.get(base + "/" + new_path, allow_redirects=False, timeout=15)
    check("redirect hit -> 302", r.status_code == 302, "got %s" % r.status_code)
    check("redirect Location correct", r.headers.get("Location") == dest,
          "got %s" % r.headers.get("Location"))

    r = requests.get(base + "/nope-%s" % suffix, allow_redirects=False, timeout=15)
    check("redirect miss -> 404", r.status_code == 404, "got %s" % r.status_code)

    if not verify_aws:
        print("\n(--verify-aws not set: skipping v2/TTL/copy-forward/metric checks)")
        return finish(base, secret, [new_path], [], verify_aws=False)

    # ---- AWS-backed cases (real DynamoDB / CloudWatch) ----
    import models
    from datetime import datetime, timedelta, timezone
    import pytz
    import boto3
    from constants import AWS_REGION, METRIC_NAMESPACE, METRIC_NAME

    # v2 row written with a seconds-epoch TTL ~90d out
    v2 = models.ShortURLV2.get(new_path)
    now = int(time.time())
    check("new link written to v2", v2.redirection_url == dest)
    check("expires_at is ~90d out in SECONDS",
          (now + 80 * 86400) < int(v2.expires_at) < (now + 100 * 86400),
          "expires_at=%s" % v2.expires_at)

    # legacy v1-only row -> redirect should copy it forward, preserving created_at
    created = datetime(2024, 1, 1, tzinfo=pytz.UTC)
    models.ShortURL(url=legacy_path, redirection_url=dest, created_at=created).save()
    r = requests.get(base + "/" + legacy_path, allow_redirects=False, timeout=15)
    check("legacy redirect -> 302", r.status_code == 302, "got %s" % r.status_code)
    time.sleep(1)
    copied = models.ShortURLV2.get(legacy_path)
    check("legacy copied into v2", copied.redirection_url == dest)
    check("copy preserves created_at", copied.created_at == created,
          "created_at=%s" % copied.created_at)

    # metric emitted in the env-scoped namespace
    cw = boto3.client("cloudwatch", region_name=AWS_REGION)
    stats = cw.get_metric_statistics(
        Namespace=METRIC_NAMESPACE, MetricName=METRIC_NAME,
        StartTime=datetime.now(timezone.utc) - timedelta(minutes=10),
        EndTime=datetime.now(timezone.utc) + timedelta(minutes=10),
        Period=3600, Statistics=["SampleCount"],
    )
    samples = sum(d["SampleCount"] for d in stats.get("Datapoints", []))
    check("age metric emitted in %s" % METRIC_NAMESPACE, samples >= 1,
          "samples=%s" % samples)

    return finish(base, secret, [new_path], [legacy_path], verify_aws=True)


def finish(base, secret, v2_paths, v1_paths, verify_aws):
    if verify_aws:
        import models
        for p in v2_paths + v1_paths:
            try:
                models.ShortURLV2.get(p).delete()
            except Exception:
                pass
        for p in v1_paths:
            try:
                models.ShortURL.get(p).delete()
            except Exception:
                pass
    failed = [n for n, ok, _ in RESULTS if not ok]
    print("\n%d passed, %d failed" % (len(RESULTS) - len(failed), len(failed)))
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. https://slink.delight.chat")
    ap.add_argument("--secret", required=True, help="SHORT_URL_SECRET_KEY for that env")
    ap.add_argument("--verify-aws", action="store_true",
                    help="also check DynamoDB/CloudWatch (needs creds; set ENVIRONMENT)")
    args = ap.parse_args()
    sys.exit(run(args.base_url, args.secret, args.verify_aws))


if __name__ == "__main__":
    main()
