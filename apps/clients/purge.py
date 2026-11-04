"""Остаточне видалення клієнтів і тварин (31.10.2026, наказ Олега).

Раніше «Видалити» лише ховало запис в архів, хоча сторінка підтвердження обіцяла
«назавжди». Тепер видаляємо по-справжньому: усю медичну історію і файли з диска
(Django сам файли не прибирає). Рахунки — фінансові документи: клієнта з рахунками
видаляємо лише разом із ними, за явним вибором адміна, так само як розділ «Рахунки»
(оплачений — з поверненням товарів на склад або без).
"""
from django.db import transaction
from django.db.models import Sum

from .models import Client, Patient, PatientAnalysis, PatientDocument, Visit
from .models_health import HealthCheck


def _invoice_model():
    from apps.billing.models import Invoice
    return Invoice


def _appointment_model():
    from apps.appointments.models import Appointment
    return Appointment


def _files_of(patients):
    """(storage, name) усіх файлів цих тварин."""
    pids = [p.pk for p in patients]
    files = [(p.photo.storage, p.photo.name) for p in patients if p.photo]
    for model, field in ((PatientAnalysis, 'image'), (PatientDocument, 'file'), (HealthCheck, 'response_photo')):
        for obj in model._base_manager.filter(patient_id__in=pids).exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}):
            f = getattr(obj, field)
            files.append((f.storage, f.name))
    return files


def _drop_files_after_commit(files):
    def _drop():
        for storage, name in files:
            try:
                storage.delete(name)
            except Exception:
                pass
    transaction.on_commit(_drop)


def patient_summary(patient):
    return {
        'visits': Visit._base_manager.filter(patient=patient).count(),
        'files': len(_files_of([patient])),
        'invoices': _invoice_model()._base_manager.filter(patient=patient).count(),
    }


def client_summary(client):
    from apps.billing.models import Invoice
    patients = list(Patient._base_manager.filter(client=client))
    inv = Invoice._base_manager.filter(client=client)
    paid = inv.filter(status=Invoice.Status.PAID)
    return {
        'patients': len(patients),
        'visits': Visit._base_manager.filter(patient__in=patients).count(),
        'files': len(_files_of(patients)),
        'appointments': _appointment_model()._base_manager.filter(client=client).count(),
        'invoices': inv.count(),
        'paid': paid.count(),
        'paid_sum': paid.aggregate(s=Sum('total'))['s'] or 0,
        'fiscal_sent': inv.filter(fiscal_status=Invoice.FiscalStatus.SENT).count(),
        'paid_written_off': paid.filter(lines__stock_written_off=True).distinct().count(),
    }


def delete_patient(patient):
    files = _files_of([patient])
    with transaction.atomic():
        patient.delete()          # рахунки лишаються за клієнтом (patient → NULL)
        _drop_files_after_commit(files)


def delete_client(client, user, *, with_invoices=False, restore_stock=False):
    from apps.billing.models import Invoice
    from apps.billing.views import _restore_stock_from_invoice
    patients = list(Patient._base_manager.filter(client=client))
    files = _files_of(patients)
    with transaction.atomic():
        invoices = list(Invoice._base_manager.filter(client=client))
        if invoices and not with_invoices:
            raise ValueError('client has invoices')
        for inv in invoices:
            if inv.status == Invoice.Status.PAID and restore_stock:
                _restore_stock_from_invoice(inv, user)
            inv.delete()
        client.delete()           # тварини, прийоми, записи в розкладі — каскадом
        _drop_files_after_commit(files)
    return len(patients), len(invoices)


def purge_archive(org):
    """Видалити все з архіву клініки, крім архівних клієнтів із рахунками
    (їх — лише по одному, з явним вибором щодо рахунків). Повертає звіт."""
    from apps.billing.models import Invoice
    clients = Client._base_manager.filter(organization=org, is_archived=True)
    with_inv = set(Invoice._base_manager.filter(client__in=clients).values_list('client_id', flat=True))
    # з історією депозиту — теж лише по одному (гроші клієнта в касі; ANVAR 04.11.2026)
    from apps.billing.models import ClientDeposit
    with_inv |= set(ClientDeposit._base_manager.filter(client__in=clients).values_list('client_id', flat=True))
    removed_clients = removed_patients = 0
    kept = []
    for c in clients:
        if c.pk in with_inv:
            kept.append(c)
            continue
        n_p, _ = delete_client(c, None)
        removed_clients += 1
        removed_patients += n_p
    # архівні тварини активних клієнтів і клієнтів, яких лишили через рахунки
    for p in Patient._base_manager.filter(client__organization=org, is_archived=True):
        delete_patient(p)
        removed_patients += 1
    return {'clients': removed_clients, 'patients': removed_patients, 'kept': kept}


def archive_counts(org):
    from apps.billing.models import Invoice
    clients = Client._base_manager.filter(organization=org, is_archived=True)
    return {
        'clients': clients.count(),
        'clients_with_invoices': Invoice._base_manager.filter(client__in=clients).values('client_id').distinct().count(),
        'patients': Patient._base_manager.filter(client__organization=org, is_archived=True).count(),
    }
