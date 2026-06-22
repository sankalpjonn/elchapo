"""
DynamoDB models for the elchapo URL shortener.

v1 (`ShortURL`)   - legacy table, read-only during the copy-forward migration.
v2 (`ShortURLV2`) - new table, carries a `expires_at` TTL attribute. All new
                    writes (and copied-forward legacy links) go here.

Tables are pre-created out of band (see ops/create_v2_table.py); we deliberately
do NOT create/describe tables at import time (that hit AWS on every cold start).
"""
from pynamodb.attributes import (
    UnicodeAttribute, UTCDateTimeAttribute, NumberAttribute
)
from pynamodb.models import Model

from constants import ENV, AWS_REGION
from utils import get_now


def create_table_name(table_name):
    """
    namespace a table name with the environment (e.g. production-<name>).
    """
    return '%s-%s' % (ENV, table_name)


class ShortURL(Model):
    """
    v1 legacy short-url store. Read-only during migration; deleted at the end.
    """

    class Meta:
        table_name = create_table_name("el-chapo-short-url-store")
        region = AWS_REGION

    url = UnicodeAttribute(hash_key=True, null=False)
    redirection_url = UnicodeAttribute(null=False)
    webhook = UnicodeAttribute(null=True)
    created_at = UTCDateTimeAttribute(default=get_now)


class ShortURLV2(Model):
    """
    v2 short-url store with a native-TTL `expires_at` (epoch seconds).
    """

    class Meta:
        table_name = create_table_name("el-chapo-short-url-store-v2")
        region = AWS_REGION

    url = UnicodeAttribute(hash_key=True, null=False)
    redirection_url = UnicodeAttribute(null=False)
    webhook = UnicodeAttribute(null=True)
    created_at = UTCDateTimeAttribute(default=get_now)
    expires_at = NumberAttribute(null=True)
