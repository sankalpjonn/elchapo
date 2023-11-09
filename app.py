import logging

import requests, os
from flask import Flask, redirect, jsonify
from flask import request

from constants import WEBHOOK, NOT_FOUND_URL, SECRET_KEY
from models import ShortURL
from zappa.asynchronous import task

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
    try:
        ShortURL.get(path)
        return "", 409
    except ShortURL.DoesNotExist:
        ShortURL(url=path, redirection_url=redirect_url, webhook=webhook).save()
        return jsonify(success=True), 200
    return "", 400


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
        if webhook.__contains__('?'):
            webhook += '&path=%s' % path
        else:
            webhook += '?path=%s' % path
    return webhook


@app.route('/<path:path>', methods=['GET'])
def redirect_url(path):
    try:
        short_url = ShortURL.get(path)
        webhook = WEBHOOK
        if short_url.webhook:
            webhook = short_url.webhook
        webhook = get_hook(webhook, path)
        if webhook:
            call_url(webhook)
        return redirect(short_url.redirection_url, code=302)
    except ShortURL.DoesNotExist:
        return jsonify(error="Not found"), 404


# We only need this for local development.
if __name__ == '__main__':
    MAIN = True
    app.run(host='0.0.0.0', port=5601)
