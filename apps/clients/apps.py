from django.apps import AppConfig

class ClientsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.clients'

    def ready(self):
        from .audit import register_audit
        from .models import Patient, Visit, Vaccine, Prescription, WeightRecord, Hospitalization
        for model in [Patient, Visit, Vaccine, Prescription, WeightRecord, Hospitalization]:
            register_audit(model)
