"""Генерація vCard 3.0 з Client + first Patient.

Формат сумісний з Android (DAVx⁵) і iOS native CardDAV.
Кожен vCard містить:
  - FN, N — імʼя/прізвище клієнта
  - TEL;TYPE=CELL — телефон у E.164
  - ORG — "Kizuna · <pet_name> (<species>)" або "Kizuna"
  - NOTE — знижка, кількість тваринок, нотатки
  - PHOTO — base64-фото першого пацієнта (256×256 JPEG, якщо є)
  - UID — стабільний UUID на основі client.pk (для sync)
  - REV — timestamp останньої зміни (для ETag)
"""
import hashlib
import io
import re
from typing import Optional

from django.utils import timezone


_SPECIES_RU = {
    'dog': 'Собака', 'cat': 'Кіт', 'rabbit': 'Кролик', 'bird': 'Птах',
    'hamster': 'Хом\'як', 'guinea_pig': 'Морська свинка', 'ferret': 'Тхір',
    'chinchilla': 'Шиншила', 'rat': 'Щур', 'turtle': 'Черепаха',
    'reptile': 'Ящ./Змія', 'fish': 'Риба', 'hedgehog': 'Їжак', 'other': 'Інше',
}


def normalize_phone_e164(raw: str) -> str:
    """'+38 (050) 123-45-67' → '+380501234567'. Якщо без + і починається з 0 → +380."""
    if not raw:
        return ''
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return ''
    # Якщо вже з кодом країни (12 цифр для UA)
    if raw.strip().startswith('+'):
        return '+' + digits
    # Українські локальні: 0XXXXXXXXX → +380XXXXXXXXX
    if digits.startswith('0') and len(digits) == 10:
        return '+38' + digits
    if digits.startswith('380') and len(digits) == 12:
        return '+' + digits
    # Інакше — як є з плюсом
    return '+' + digits


def _escape(value: str) -> str:
    """vCard escape: \\, , ; → \\\\, \\, , \\;."""
    if not value:
        return ''
    return (
        value.replace('\\', '\\\\')
             .replace(';', '\\;')
             .replace(',', '\\,')
             .replace('\n', '\\n')
    )


def _patient_photo_b64(patient) -> Optional[str]:
    """Resize фото пацієнта до 256×256 JPEG quality=80, base64-encoded."""
    if not patient or not patient.photo:
        return None
    try:
        from PIL import Image
        with Image.open(patient.photo.path) as img:
            img = img.convert('RGB')
            img.thumbnail((256, 256))
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=80, optimize=True)
            import base64
            return base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return None


def client_uid(client) -> str:
    """Стабільний UID для vCard. Формат: kizuna-<org_id>-<client_pk>@kizuna.crm"""
    org_id = getattr(client, 'organization_id', None) or 0
    return f'kizuna-{org_id}-{client.pk}@kizuna.crm'


def client_etag(client, patient=None) -> str:
    """ETag для sync — змінюється коли client/patient/photo змінились."""
    parts = [
        str(client.pk),
        str(client.first_name),
        str(client.last_name),
        str(client.phone),
        str(client.email or ''),
        str(client.discount_percent or 0),
        str(client.notes or '')[:200],
    ]
    if patient:
        parts.append(str(patient.pk))
        parts.append(str(patient.name))
        parts.append(str(patient.species))
        if patient.photo:
            try:
                parts.append(str(patient.photo.name))
                parts.append(str(int(patient.photo.size)))
            except Exception:
                pass
    digest = hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()
    return f'"{digest[:16]}"'


def _fold_line(line: str, limit: int = 75) -> str:
    """vCard line folding RFC 6350: рядки >75 байт згортаються з \r\n продовженням від пробілу."""
    encoded = line.encode('utf-8')
    if len(encoded) <= limit:
        return line
    parts = []
    while len(encoded) > limit:
        # шукаємо boundary що не ламає UTF-8 character
        chunk = encoded[:limit]
        # decode без error — обрізаємо назад до valid boundary
        while True:
            try:
                parts.append(chunk.decode('utf-8'))
                break
            except UnicodeDecodeError:
                chunk = chunk[:-1]
        encoded = encoded[len(chunk):]
    parts.append(encoded.decode('utf-8'))
    return '\r\n '.join(parts)


def render_vcard(client) -> str:
    """Згенерувати vCard 3.0 для клієнта.

    Patient — перший активний (не архівований) `client.patients.first()`.
    """
    # Перший пацієнт (active)
    try:
        patient = client.patients.filter(is_archived=False).first()
    except Exception:
        patient = None

    full_name = f'{(client.last_name or "").strip()} {(client.first_name or "").strip()}'.strip()
    phone = normalize_phone_e164(client.phone or '')

    # ORG = "{назва клініки} · {pet_name} ({species})" — назва береться з організації
    # клієнта, а не хардкодом, інакше контакти чужої клініки підписані як Kizuna.
    _org = getattr(client, 'organization', None)
    clinic_label = (
        (getattr(_org, 'short_name', '') or getattr(_org, 'name', '') or 'Клініка').strip()
    )
    if patient:
        species = _SPECIES_RU.get(patient.species, patient.species or '')
        org_label = f'{clinic_label} · {patient.name} ({species})'
    else:
        org_label = clinic_label

    # NOTE
    note_parts = []
    if patient:
        try:
            count = client.patients.filter(is_archived=False).count()
        except Exception:
            count = 1
        if count > 1:
            note_parts.append(f'Тваринок: {count}')
    if client.discount_percent and float(client.discount_percent) > 0:
        note_parts.append(f'Знижка {client.discount_percent}%')
    if client.notes:
        note_parts.append(client.notes[:200])
    note = ' · '.join(note_parts)

    lines = [
        'BEGIN:VCARD',
        'VERSION:3.0',
        f'PRODID:-//Kizuna CRM//CardDAV//UK',
        f'UID:{client_uid(client)}',
        f'FN:{_escape(full_name or client.phone)}',
        f'N:{_escape(client.last_name or "")};{_escape(client.first_name or "")};;;',
    ]
    if phone:
        lines.append(f'TEL;TYPE=CELL:{phone}')
    if client.email:
        lines.append(f'EMAIL:{_escape(client.email)}')
    lines.append(f'ORG:{_escape(org_label)}')
    if note:
        lines.append(f'NOTE:{_escape(note)}')

    # PHOTO — base64-inline (Android підтримує)
    photo_b64 = _patient_photo_b64(patient)
    if photo_b64:
        lines.append(f'PHOTO;ENCODING=b;TYPE=JPEG:{photo_b64}')

    # REV — час останньої модифікації (для дебагу)
    now = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    lines.append(f'REV:{now}')
    lines.append('END:VCARD')

    # Fold long lines (PHOTO часто 5-50KB)
    folded = [_fold_line(l) for l in lines]
    return '\r\n'.join(folded) + '\r\n'
