"""
store all constants for lambda
"""
import os

ENV = os.getenv('ENVIRONMENT', 'production')
SECRET_KEY = os.getenv('SECRET_KEY', 'somekey')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

WEBHOOK = os.getenv('WEBHOOK', None)
NOT_FOUND_URL = os.getenv('NOT_FOUND_URL', "https://github.com/sankalpjonn/elchapo")

# DynamoDB TTL window for short links (days).
TTL_DAYS = int(os.getenv('TTL_DAYS', 90))

# CloudWatch metric for measuring the age of still-clicked legacy links.
# Namespace is environment-scoped (Elchapo/production vs Elchapo/staging) so
# staging and production are differentiated WITHOUT any dimensions -> exactly
# one metric stream per environment, ~$0.30/mo each.
METRIC_NAME = 'ActiveLinkAgeDays'
METRIC_NAMESPACE = 'Elchapo/%s' % ENV
