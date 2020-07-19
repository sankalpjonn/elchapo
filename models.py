"""
model for lmabda
"""
from pynamodb.attributes import (
    UnicodeAttribute, UTCDateTimeAttribute, BooleanAttribute
)
from pynamodb.models import Model

from constants import ENV, AWS_REGION
from utils import get_now


def create_table_name(table_name):
    """
    create table to name for dynamodb
    """
    return '%s-%s' % (ENV, table_name)


class ShortURL(Model):
    """
    A DynamoDB VideoWatch
    """

    class Meta:
        """
        set meta of table
        """
        table_name = create_table_name("el-chapo-short-url-store")
        region = AWS_REGION

    url = UnicodeAttribute(hash_key=True, null=False)
    redirection_url = UnicodeAttribute(null=False)
    webhook = UnicodeAttribute(null=True)
    created_at = UTCDateTimeAttribute(default=get_now())


# automatically creates a table in dynamo db if doesnt exist.
if not ShortURL.exists():
    ShortURL.create_table(wait=True, billing_mode="PAY_PER_REQUEST")
