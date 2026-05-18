import os
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('SECRET_KEY')

# WayForPay
WAYFORPAY_MERCHANT = config('WAYFORPAY_MERCHANT', default='')
WAYFORPAY_SECRET = config('WAYFORPAY_SECRET', default='')

# Email
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='localhost')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='Kizuna CRM <crm@kizuna.com.ua>')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third party
    'django_htmx',
    'django_celery_beat',
    'axes',
    # apps
    'apps.clinic',
    'apps.accounts',
    'apps.clients',
    'apps.inventory',
    'apps.services',
    'apps.billing',
    'apps.tg',
    'apps.appointments',
    'apps.analytics',
    'apps.finance',
    'apps.dashboard_builder',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.clients.audit.AuditMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'config.middleware.TenantMiddleware',
    # django-axes — має бути ОСТАННІМ
    'axes.middleware.AxesMiddleware',
]

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# django-axes: brute-force protection на login
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # годин
AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ADMIN = False  # не показуємо у Django admin

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.clinic.context_processors.clinic',
                'apps.inventory.context_processors.expiry_alerts',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='kizuna'),
        'USER': config('DB_USER', default='kizuna'),
        'PASSWORD': config('DB_PASSWORD', default='kizuna'),
        'HOST': config('DB_HOST', default='db'),
        'PORT': config('DB_PORT', default='5432'),
        'CONN_MAX_AGE': 60,
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.getenv('REDIS_URL', 'redis://redis:6379/1'),
    }
}
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'

AUTH_USER_MODEL = 'accounts.User'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

# Базовий домен платформи. Якщо вказано — субдомени розпізнаються як тенанти.
# Приклад: "crm.kizuna.com.ua" → "kizuna.crm.kizuna.com.ua" буде тенантом з slug="kizuna"
MAIN_DOMAIN = config('MAIN_DOMAIN', default='')

# Базова URL-адреса сайту — використовується WeasyPrint для генерації PDF через Telegram-бот.
# Якщо не вказано — береться з MAIN_DOMAIN або 'http://localhost' як fallback.
SITE_URL = config('SITE_URL', default='')

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

LANGUAGE_CODE = 'uk'
TIME_ZONE = 'Europe/Kyiv'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Celery
CELERY_BROKER_URL = config('REDIS_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = config('REDIS_URL', default='redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TIMEZONE = 'Europe/Kyiv'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_BEAT_SCHEDULE = {
    'send-vaccine-reminders-daily': {
        'task': 'apps.clients.tasks.send_vaccine_reminders',
        'schedule': 60 * 60 * 24,  # раз на добу
        'options': {'expires': 3600},
    },
    'send-appointment-reminders': {
        'task': 'apps.clients.tasks.send_appointment_reminders',
        'schedule': 60 * 30,  # кожні 30 хв
        'options': {'expires': 1800},
    },
    'send-followup-reminders': {
        'task': 'apps.clients.tasks.send_followup_reminders',
        'schedule': 60 * 60 * 24,  # раз на добу
        'options': {'expires': 3600},
    },
    'send-health-checks': {
        'task': 'apps.clients.tasks.send_health_checks',
        'schedule': 60 * 60 * 24,  # раз на добу
        'options': {'expires': 3600},
    },
}

TELEGRAM_BOT_TOKEN = config('TELEGRAM_BOT_TOKEN', default='')

CHECKBOX_API_URL = config('CHECKBOX_API_URL', default='https://api.checkbox.in.ua/api/v1')
CHECKBOX_LICENSE_KEY = config('CHECKBOX_LICENSE_KEY', default='')
CHECKBOX_PIN = config('CHECKBOX_PIN', default='')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
