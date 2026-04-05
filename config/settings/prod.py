from .base import *
from decouple import config, Csv

DEBUG = False

ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=Csv())

# Wildcard субдоменів для multi-tenant.
# Якщо MAIN_DOMAIN встановлений — автоматично додаємо .{domain} до ALLOWED_HOSTS
_main_domain = config('MAIN_DOMAIN', default='')
if _main_domain and f'.{_main_domain}' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS = list(ALLOWED_HOSTS) + [f'.{_main_domain}']

CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', cast=Csv(), default='https://crm.kizuna.com.ua')

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
