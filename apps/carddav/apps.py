from django.apps import AppConfig


class CarddavConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.carddav'
    verbose_name = 'CardDAV (синхронізація контактів)'
