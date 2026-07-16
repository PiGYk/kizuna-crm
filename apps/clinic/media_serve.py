"""Protected media serving via nginx X-Accel-Redirect."""
import logging
import os
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse

logger = logging.getLogger(__name__)


@login_required
def serve_media(request, path):
    """
    Захищена роздача медіафайлів через nginx X-Accel-Redirect.

    Nginx повинен мати location /media/ з директивою internal;
    Для нових шляхів (org_{pk}/...) перевіряє приналежність до поточного тенанта.
    Для старих шляхів (patients/, analyses/ тощо) — достатньо login_required.
    """
    # Захист від path traversal
    safe_path = os.path.normpath(path)
    if safe_path.startswith('..') or os.path.isabs(safe_path):
        raise Http404

    full_path = os.path.join(settings.MEDIA_ROOT, safe_path)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise Http404

    # Org-ізоляція для нових шляхів виду org_{pk}/...
    if safe_path.startswith('org_'):
        first_segment = safe_path.split('/')[0]  # 'org_5'
        try:
            path_org_pk = int(first_segment[4:])  # strip 'org_'
        except (ValueError, IndexError):
            raise Http404

        user_org = getattr(request, 'organization', None)
        if user_org is None or user_org.pk != path_org_pk:
            logger.warning(
                'serve_media: user %s (org=%s) attempted to access org_%s resource: %s',
                request.user, getattr(user_org, 'pk', None), path_org_pk, safe_path
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
