from django.apps import AppConfig

class ClientsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.clients'

    def ready(self):
        from .audit import register_audit
        from .models import Patient, Visit, Vaccine, Prescription, WeightRecord, Hospitalization
        for model in [Patient, Visit, Vaccine, Prescription, WeightRecord, Hospitalization]:
            register_audit(model)
        # Графік змін правлять усі працівники (з 18.10), а з нього рахується
        # зарплата — тож хто кого поставив чи зняв, мусить лишатись у журналі.
        from apps.accounts.models_payroll import Shift
        register_audit(Shift)
