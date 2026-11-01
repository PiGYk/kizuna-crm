"""Protected media serving via nginx X-Accel-Redirect."""
import logging
import os
import re
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse

logger = logging.getLogger(__name__)

# Старі шляхи без org_{pk}/ (файли до переходу на теки клінік, а документи пацієнтів — і досі
# до 01.11.2026). Раніше їх віддавали будь-кому, хто увійшов, — тобто і чужій клініці: 01.11
# користувач ANVAR відкрив документ пацієнта Kizuna за прямою адресою. Тепер власника шукаємо
# в базі: файл віддаємо, лише якщо на нього посилається запис своєї клініки.
_LEGACY_OWNERS = {
    'patients/': (('clients.PatientDocument', 'file', 'patient__client__organization_id'),
                  ('clients.Patient', 'photo', 'client__organization_id')),
    'analyses/': (('clients.PatientAnalysis', 'image', 'patient__client__organization_id'),),
    'tg_media/': (('tg.TelegramMessage', 'media_file', 'chat__organization_id'),),
    'expenses/': (('finance.Expense', 'receipt_photo', 'organization_id'),),
    'health_checks/': (('clients.HealthCheck', 'response_photo', 'organization_id'),),
}
# картинки довідки — спільні для всіх клінік
_SHARED_PREFIXES = ('help-screens/',)


def _legacy_owner_pk(path):
    """Номер клініки, чий запис посилається на файл; None — не знайдено або шлях невідомий."""
    from django.apps import apps
    for prefix, sources in _LEGACY_OWNERS.items():
        if path.startswith(prefix):
            for label, field, org_field in sources:
                owner = (apps.get_model(label)._base_manager.filter(**{field: path})
                         .values_list(org_field, flat=True).first())
                if owner:
                    return owner
            return None
    return None


@login_required
def serve_media(request, path):
    """
    Захищена роздача медіафайлів через nginx X-Accel-Redirect.

    Nginx повинен мати location /media/ з директивою internal;
    Шляхи org_{pk}/... — лише своїй клініці. Старі шляхи (patients/, analyses/ тощо) — лише
    клініці, чий запис у базі на файл посилається. Невідомі шляхи — лише суперкористувачу.
    """
    # Захист від path traversal
    safe_path = os.path.normpath(path)
    if safe_path.startswith('..') or os.path.isabs(safe_path):
        raise Http404

    full_path = os.path.join(settings.MEDIA_ROOT, safe_path)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise Http404

    # Org-ізоляція для нових шляхів виду org_{pk}/...
    user_org = getattr(request, 'organization', None)
    m = re.match(r'org_(\d+)/', safe_path)
    if m:
        path_org_pk = int(m.group(1))
        if user_org is None or user_org.pk != path_org_pk:
            logger.warning(
                'serve_media: user %s (org=%s) attempted to access org_%s resource: %s',
                request.user, getattr(user_org, 'pk', None), path_org_pk, safe_path
            )
            raise Http404
    elif safe_path.startswith('org_logos/'):
        # Логотипи до 31.10.2026 лягали в спільну теку. Раніше 'org_logos' розбирався
        # як номер клініки «logos» і падав у 404 — логотип не показувався ніколи.
        # Віддаємо лише логотип своєї клініки.
        own = user_org.logo.name if (user_org is not None and user_org.logo) else ''
        if own != safe_path:
            raise Http404
    elif safe_path.startswith('org_'):
        raise Http404
    elif safe_path.startswith(_SHARED_PREFIXES):
        pass
    elif not request.user.is_superuser:
        owner = _legacy_owner_pk(safe_path)
        if user_org is None or owner != user_org.pk:
            logger.warning(
                'serve_media: user %s (org=%s) denied legacy resource (owner org=%s): %s',
                request.user, getattr(user_org, 'pk', None), owner, safe_path
            )
            raise Http404

    response = HttpResponse(status=200)
    # quote(): percent-encode шлях (кирилиця/не-ASCII) — інакше Django загортає
    # заголовок X-Accel-Redirect у RFC2047 (=?utf-8?b?...?=), а nginx це не
    # розкодовує і віддає 404, хоча файл фізично існує.
    response['X-Accel-Redirect'] = f'/x-media/{quote(safe_path)}'
    # Видаляємо CT — порожній рядок змушує nginx відправляти text/html для mp4.
    # Без хедера nginx сам визначить Content-Type через mime.types.
    del response['Content-Type']
    return response
