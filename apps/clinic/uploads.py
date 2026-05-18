"""Upload path callables для per-organization ізоляції медіафайлів."""


def patient_photo_path(instance, filename):
    try:
        org_pk = instance.client.organization_id or 0
    except Exception:
        org_pk = 0
    return f'org_{org_pk}/patients/{filename}'


def analysis_image_path(instance, filename):
    try:
        org_pk = instance.patient.client.organization_id or 0
    except Exception:
        org_pk = 0
    return f'org_{org_pk}/analyses/{filename}'


def expense_receipt_path(instance, filename):
    org_pk = instance.organization_id or 0
    return f'org_{org_pk}/expenses/{filename}'


def tg_media_path(instance, filename):
    try:
        org_pk = instance.chat.organization_id or 0
    except Exception:
        org_pk = 0
    return f'org_{org_pk}/tg_media/{filename}'


def org_logo_path(instance, filename):
    import os
    ext = os.path.splitext(filename)[1].lower()
    return f'org_{instance.pk}/logo{ext}'
