"""Minimal CardDAV server для caller ID на телефоні.

Реалізовано лише read-only flow для DAVx⁵ (Android):
  - OPTIONS — header DAV: 1, 3, addressbook
  - PROPFIND на /carddav/{username}/ — principal collection
  - PROPFIND на /carddav/{username}/addressbooks/ — home set
  - PROPFIND на /carddav/{username}/addressbooks/clients/ — addressbook (Depth: 0|1)
  - REPORT на addressbook (sync-collection / addressbook-multiget)
  - GET на .vcf — окремий vcard

Не реалізовано: PUT/DELETE (не треба для caller ID).
"""
import logging
import re
from xml.sax.saxutils import escape as xml_escape

from django.http import HttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.clients.models import Client

from .auth import carddav_auth
from .vcard import client_uid, client_etag, render_vcard

logger = logging.getLogger(__name__)


# ── Хелпери ──────────────────────────────────────────────────────────────────

def _xml_response(body: str, status: int = 207) -> HttpResponse:
    resp = HttpResponse(body, content_type='application/xml; charset=utf-8', status=status)
    resp['DAV'] = '1, 3, addressbook'
    return resp


def _abs_url(request, path: str) -> str:
    """Повертає абсолютний URL з тим самим scheme/host що у request."""
    return request.build_absolute_uri(path).rstrip('/')


def _vcard_href(request, username: str, client_pk: int) -> str:
    return f'/carddav/{username}/addressbooks/clients/{client_pk}.vcf'


def _client_qs_for(user):
    """Активні (не архівовані) клієнти org з телефоном — для caller ID нема сенсу без номера."""
    org = user.organization
    if not org:
        return Client.objects.none()
    return (
        Client.objects.filter(organization=org, is_archived=False)
        .exclude(phone='')
        .prefetch_related('patients')
        .order_by('pk')
    )


# ── OPTIONS — discovery ──────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['OPTIONS'])
def options(request, username=None):
    resp = HttpResponse(status=200)
    resp['DAV'] = '1, 3, addressbook'
    resp['Allow'] = 'OPTIONS, GET, HEAD, PROPFIND, REPORT'
    resp['Content-Length'] = '0'
    return resp


# ── PROPFIND ─────────────────────────────────────────────────────────────────

def _principal_propfind(request, username):
    """PROPFIND на /carddav/{username}/ → principal-URL + home-set."""
    principal_url = _abs_url(request, f'/carddav/{username}/')
    home_url = _abs_url(request, f'/carddav/{username}/addressbooks/')
    body = f'''<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:response>
    <d:href>/carddav/{xml_escape(username)}/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/><d:principal/></d:resourcetype>
        <d:displayname>{xml_escape(username)}</d:displayname>
        <d:current-user-principal><d:href>{principal_url}/</d:href></d:current-user-principal>
        <card:addressbook-home-set><d:href>{home_url}/</d:href></card:addressbook-home-set>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>'''
    return _xml_response(body, 207)


def _home_propfind(request, username, depth):
    """PROPFIND на /addressbooks/ → list of addressbook collections (1 — "clients")."""
    home_url = _abs_url(request, f'/carddav/{username}/addressbooks/')
    book_url = _abs_url(request, f'/carddav/{username}/addressbooks/clients/')

    responses = [f'''  <d:response>
    <d:href>/carddav/{xml_escape(username)}/addressbooks/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/></d:resourcetype>
        <d:displayname>Addressbooks</d:displayname>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>''']

    if depth in ('1', 'infinity'):
        responses.append(_addressbook_propstat_xml(request, username))

    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">\n'
        + '\n'.join(responses)
        + '\n</d:multistatus>'
    )
    return _xml_response(body, 207)


def _addressbook_propstat_xml(request, username):
    book_url = _abs_url(request, f'/carddav/{username}/addressbooks/clients/')
    from .models import CardDAVToken
    user = request.carddav_user
    cdt = CardDAVToken.get_or_create_for(user)
    return f'''  <d:response>
    <d:href>/carddav/{xml_escape(username)}/addressbooks/clients/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/><card:addressbook/></d:resourcetype>
        <d:displayname>Kizuna Clients</d:displayname>
        <card:addressbook-description>Клієнти ветклініки {xml_escape(user.organization.name if user.organization else "Kizuna")}</card:addressbook-description>
        <card:supported-address-data>
          <card:address-data-type content-type="text/vcard" version="3.0"/>
        </card:supported-address-data>
        <d:sync-token>http://kizuna.crm/sync/{cdt.sync_token}</d:sync-token>
        <d:supported-report-set>
          <d:supported-report><d:report><card:addressbook-multiget/></d:report></d:supported-report>
          <d:supported-report><d:report><d:sync-collection/></d:report></d:supported-report>
        </d:supported-report-set>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>'''


def _addressbook_propfind(request, username, depth):
    """PROPFIND на /addressbooks/clients/ — addressbook collection.

    Depth: 0 → лише сама колекція.
    Depth: 1 → колекція + всі vcards (з ETag, без бодика; DAVx⁵ потім зробить multiget).
    """
    responses = [_addressbook_propstat_xml(request, username)]

    if depth in ('1', 'infinity'):
        for client in _client_qs_for(request.carddav_user):
            patient = client.patients.filter(is_archived=False).first()
            etag = client_etag(client, patient)
            href = _vcard_href(request, username, client.pk)
            responses.append(f'''  <d:response>
    <d:href>{href}</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype/>
        <d:getetag>{etag}</d:getetag>
        <d:getcontenttype>text/vcard; charset=utf-8</d:getcontenttype>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>''')

    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">\n'
        + '\n'.join(responses)
        + '\n</d:multistatus>'
    )
    return _xml_response(body, 207)


@csrf_exempt
def propfind(request, username, sub=''):
    """Розводить PROPFIND по 3 рівнях URL."""
    if request.method != 'PROPFIND':
        return HttpResponse(status=405)

    depth = request.META.get('HTTP_DEPTH', '0')
    sub = (sub or '').strip('/')

    if sub == '':
        return _principal_propfind(request, username)
    if sub == 'addressbooks':
        return _home_propfind(request, username, depth)
    if sub == 'addressbooks/clients':
        return _addressbook_propfind(request, username, depth)

    return HttpResponse(status=404)


# ── REPORT (addressbook-multiget + sync-collection) ──────────────────────────

_HREF_RE = re.compile(r'<(?:[a-zA-Z]+:)?href[^>]*>([^<]+)</(?:[a-zA-Z]+:)?href>')


@csrf_exempt
def report(request, username, sub=''):
    if request.method != 'REPORT':
        return HttpResponse(status=405)

    body = request.body.decode('utf-8', errors='replace')

    # Це addressbook-multiget — DAVx⁵ просить кілька vcards за href.
    if 'addressbook-multiget' in body:
        return _multiget_report(request, username, body)

    # sync-collection — DAVx⁵ опитує "що змінилось". Для MVP — повертаємо ВСЕ як changed.
    if 'sync-collection' in body:
        return _sync_collection_report(request, username, body)

    return HttpResponse(status=400)


def _multiget_report(request, username, body):
    hrefs = _HREF_RE.findall(body)
    pk_set = set()
    for href in hrefs:
        m = re.search(r'/clients/(\d+)\.vcf$', href)
        if m:
            pk_set.add(int(m.group(1)))

    qs = _client_qs_for(request.carddav_user).filter(pk__in=pk_set)
    responses = []
    for client in qs:
        patient = client.patients.filter(is_archived=False).first()
        etag = client_etag(client, patient)
        href = _vcard_href(request, username, client.pk)
        vcard_text = render_vcard(client)
        responses.append(f'''  <d:response>
    <d:href>{href}</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>{etag}</d:getetag>
        <card:address-data>{xml_escape(vcard_text)}</card:address-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>''')

    body_out = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">\n'
        + '\n'.join(responses)
        + '\n</d:multistatus>'
    )
    return _xml_response(body_out, 207)


def _sync_collection_report(request, username, body):
    """Для MVP: повертаємо всіх клієнтів як "змінені", + новий sync-token.

    DAVx⁵ після цього зробить multiget. Якщо хочемо реальний incremental sync —
    треба зберігати changelog (created/updated/deleted) у БД. Для caller ID
    full sync кожен раз = OK (десятки-сотні клієнтів, 5-15 хв cycle).
    """
    from .models import CardDAVToken
    user = request.carddav_user
    cdt = CardDAVToken.get_or_create_for(user)

    responses = []
    for client in _client_qs_for(user):
        patient = client.patients.filter(is_archived=False).first()
        etag = client_etag(client, patient)
        href = _vcard_href(request, username, client.pk)
        responses.append(f'''  <d:response>
    <d:href>{href}</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>{etag}</d:getetag>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>''')

    sync_token_url = f'http://kizuna.crm/sync/{cdt.sync_token}'
    body_out = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">\n'
        + '\n'.join(responses)
        + f'\n  <d:sync-token>{sync_token_url}</d:sync-token>\n'
        + '</d:multistatus>'
    )
    return _xml_response(body_out, 207)


# ── GET — одна vCard ─────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET', 'HEAD'])
def get_vcard(request, username, client_pk):
    qs = _client_qs_for(request.carddav_user)
    try:
        client = qs.get(pk=int(client_pk))
    except (Client.DoesNotExist, ValueError):
        raise Http404
    patient = client.patients.filter(is_archived=False).first()
    etag = client_etag(client, patient)

    # If-None-Match (304 short-circuit)
    if request.META.get('HTTP_IF_NONE_MATCH') == etag:
        resp = HttpResponse(status=304)
        resp['ETag'] = etag
        return resp

    vcard_text = render_vcard(client)
    resp = HttpResponse(vcard_text, content_type='text/vcard; charset=utf-8')
    resp['ETag'] = etag
    resp['Content-Length'] = str(len(vcard_text.encode('utf-8')))
    return resp


# ── Router-views (decorated з auth) ──────────────────────────────────────────

@csrf_exempt
@carddav_auth
def carddav_root(request, username):
    """Router для /carddav/{username}/ — OPTIONS або PROPFIND."""
    method = request.method
    if method == 'OPTIONS':
        return options(request, username)
    if method == 'PROPFIND':
        return propfind(request, username, sub='')
    return HttpResponse(status=405)


@csrf_exempt
@carddav_auth
def carddav_home(request, username):
    """Router для /carddav/{username}/addressbooks/."""
    method = request.method
    if method == 'OPTIONS':
        return options(request, username)
    if method == 'PROPFIND':
        return propfind(request, username, sub='addressbooks')
    return HttpResponse(status=405)


@csrf_exempt
@carddav_auth
def carddav_addressbook(request, username):
    """Router для /carddav/{username}/addressbooks/clients/."""
    method = request.method
    if method == 'OPTIONS':
        return options(request, username)
    if method == 'PROPFIND':
        return propfind(request, username, sub='addressbooks/clients')
    if method == 'REPORT':
        return report(request, username, sub='addressbooks/clients')
    return HttpResponse(status=405)


@csrf_exempt
@carddav_auth
def carddav_vcard(request, username, client_pk):
    method = request.method
    if method == 'OPTIONS':
        return options(request, username)
    if method in ('GET', 'HEAD'):
        return get_vcard(request, username, client_pk)
    return HttpResponse(status=405)


# ── Well-known redirect (RFC 6764) ───────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET', 'HEAD', 'OPTIONS', 'PROPFIND'])
def well_known(request):
    """/.well-known/carddav → 301 → /carddav/

    DAVx⁵ використовує цей шлях для auto-discovery.
    """
    if request.method == 'OPTIONS':
        resp = HttpResponse(status=200)
        resp['DAV'] = '1, 3, addressbook'
        resp['Allow'] = 'OPTIONS, GET, HEAD, PROPFIND'
        return resp
    resp = HttpResponse(status=301)
    resp['Location'] = '/carddav/'
    return resp
