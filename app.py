import logging

import requests, os
import boto3
from flask import Flask, redirect, jsonify
from flask import request

from constants import (
    WEBHOOK, NOT_FOUND_URL, SECRET_KEY, METRIC_NAME, METRIC_NAMESPACE, TTL_DAYS,
    AWS_REGION,
)
from models import ShortURL, ShortURLV2
from pynamodb.exceptions import PutError
from utils import get_now, ttl_epoch_seconds
try:
    from zappa.asynchronous import task
except ImportError:
    # Local/test environments don't ship zappa. Fall back to a synchronous
    # decorator so the module is importable; in Lambda the real zappa `task`
    # is used and webhook calls run asynchronously.
    def task(fn):
        return fn

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

MAIN = False

app = Flask(__name__, static_url_path='/no_static')


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


@app.route('/c', methods=['POST'])
def create_url():
    path = request.json['path']
    secret_key = request.json.get("secret_key")
    redirect_url = request.json['redirect_url']
    webhook = request.json.get('webhook', None)
    if secret_key != SECRET_KEY:
        return "", 403
    # Grace-period guard: never reuse a path that still lives in the legacy
    # table, or a new random path could hijack an old link's destination.
    try:
        ShortURL.get(path)
        return "", 409
    except ShortURL.DoesNotExist:
        pass
    try:
        ShortURLV2(
            url=path,
            redirection_url=redirect_url,
            webhook=webhook,
            expires_at=ttl_epoch_seconds(get_now(), TTL_DAYS),
        ).save(ShortURLV2.url.does_not_exist())
        return jsonify(success=True), 200
    except PutError:
        # conditional check failed -> path already exists in v2
        return "", 409


@task
def call_url(url):
    if url:
        retry = 3
        while retry > 0:
            x = requests.get(url)
            if x.status_code >= 400:
                retry = retry - 1
            else:
                return x.text


def get_hook(webhook, path):
    if webhook:
        sep = '&' if '?' in webhook else '?'
        webhook = webhook + '%spath=%s' % (sep, path)
    return webhook


def build_v2_from_v1(v1_item, now):
    """
    Map a v1 (legacy) row to a v2 row for copy-forward.

    Preserve created_at (so the age metric is meaningful); set expires_at to
    now + TTL, NOT created_at + TTL (an old link would otherwise be born expired).
    """
    return ShortURLV2(
        url=v1_item.url,
        redirection_url=v1_item.redirection_url,
        webhook=v1_item.webhook,
        created_at=v1_item.created_at,
        expires_at=ttl_epoch_seconds(now, TTL_DAYS),
    )


def build_age_metric(created_at, now):
    """
    CloudWatch put_metric_data kwargs for ActiveLinkAgeDays.

    Value-only, NO dimensions (a dimension would multiply the billed metric
    streams), env-scoped namespace so staging/production are separated cheaply.
    """
    age_days = (now - created_at).total_seconds() / 86400.0
    return {
        'Namespace': METRIC_NAMESPACE,
        'MetricData': [{
            'MetricName': METRIC_NAME,
            'Value': age_days,
            'Unit': 'None',
        }],
    }


def emit_active_link_age(created_at, now):
    """Publish one ActiveLinkAgeDays datapoint (best-effort)."""
    cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)
    cloudwatch.put_metric_data(**build_age_metric(created_at, now))


def lookup_or_copy_forward(path):
    """
    Resolve a short path: v2 first, then legacy v1 with copy-forward.

    On a v1 hit we copy the row into v2 (preserving created_at, stamping a fresh
    TTL) and emit the age metric ONCE, on the first discovery only. Returns the
    resolved item (a ShortURLV2) or None if the path exists in neither table.
    """
    try:
        return ShortURLV2.get(path)
    except ShortURLV2.DoesNotExist:
        pass
    try:
        v1_item = ShortURL.get(path)
    except ShortURL.DoesNotExist:
        return None
    now = get_now()
    v2_item = build_v2_from_v1(v1_item, now)
    try:
        v2_item.save(ShortURLV2.url.does_not_exist())
        emit_active_link_age(v1_item.created_at, now)
    except PutError:
        # A concurrent request already copied it forward; don't double-count.
        v2_item = ShortURLV2.get(path)
    return v2_item


@app.route('/<path:path>', methods=['GET'])
def redirect_url(path):
    short_url = lookup_or_copy_forward(path)
    if short_url is None:
        return jsonify(error="Not found"), 404
    webhook = short_url.webhook or WEBHOOK
    webhook = get_hook(webhook, path)
    if webhook:
        call_url(webhook)
    return redirect(short_url.redirection_url, code=302)


@app.route('/', methods=['GET'])
def testing_this_url():
    return "sucess", 200

# We only need this for local development.
if __name__ == '__main__':
    MAIN = True
    app.run(host='0.0.0.0', port=5601)
