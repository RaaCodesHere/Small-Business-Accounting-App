import os
from datetime import timedelta

# Base directory of the project
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Flask Configuration
SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
DEBUG = os.environ.get('FLASK_ENV') == 'development'

# Database Configuration
DATABASE_PATH = os.path.join(BASE_DIR, 'hisabflow.db')
DATABASE_URL = f'sqlite:///{DATABASE_PATH}'

# Session Configuration
SESSION_TYPE = 'filesystem'
PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
SESSION_COOKIE_SECURE = not DEBUG  # HTTPS only in production
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# Application Settings
APP_NAME = 'HisabFlow'
APP_VERSION = '1.0.0'

# Constants for validation
TRANSACTION_TYPES = ('credit', 'debit')
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 50
MIN_PASSWORD_LENGTH = 6
MIN_CUSTOMER_NAME_LENGTH = 2
MAX_CUSTOMER_NAME_LENGTH = 100
MAX_PHONE_LENGTH = 20
MAX_BALANCE = 9999999.99
MIN_BALANCE = -9999999.99
