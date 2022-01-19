"""
store all constants for lambda
"""
import os

ENV = os.getenv('ENVIRONMENT', 'production')
SECRET_KEY = os.getenv('SECRET_KEY', 'somekey')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

WEBHOOK = os.getenv('WEBHOOK', None)
NOT_FOUND_URL = os.getenv('NOT_FOUND_URL', "https://github.com/sankalpjonn/elchapo")
