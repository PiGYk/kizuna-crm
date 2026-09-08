# -*- coding: utf-8 -*-
"""Читання відповідей від клінік і чернетки відповідей.

Логіка навмисно параноїдальна: у скриньці 90% сміття (dmarc-звіти, робота.ua,
фішинг «ваш рекламний акаунт заблоковано»). Тому реагуємо ЛИШЕ на листи з адрес,
які є в базі як користувачі клінік. Усе інше не існує.

Відповідь НІКОЛИ не відправляється сама — вона лягає чернеткою в Drafts і
приходить Олегу в Телеграм. Вирішує людина.
"""
import email
import imaplib
import logging
import re
import time
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.utils import parseaddr, formatdate, make_msgid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

logger = logging.getLogger(__name__)

IMAP_PORT = 993
DRAFTS = 'Drafts'
LOOKBACK_DAYS = 14          # глибше не заглядаємо — старе вже неактуальне
MAX_BODY_CHARS = 4000       # довші листи ріжемо, це вже не питання, а трактат


def _decode(value):
    try:
        return str(make_header(decode_header(value or '')))
    except Exception:
        return value or ''


def _plain_body(msg):
    """Текст листа без HTML і без цитати попередньої переписки."""
    body = ''
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain' and 'attachment' not in str(part.get('Content-Disposition', '')):
                try:
                    body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace')
                    break
                except Exception:
                    continue
    else:
        try:
            body = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', 'replace')
        except Exception:
            body = str(msg.get_payload())

    lines = []
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith('>'):                      # цитата
            continue
        if re.match(r'^-{2,}\s*(Original|Пересла|Forwarded)', s, re.I):
            break
        if re.match(r'^(\d{1,2}\.\d{1,2}\.\d{2,4}.*(пише|wrote)|On .* wrote:)', s):
            break
        lines.append(ln)
    return '\n'.join(lines).strip()[:MAX_BODY_CHARS]


def known_senders():
    """Мапа email → організація. Тільки активні клініки, без демо і власної."""
    from apps.clinic.management.commands.send_trial_emails import SKIP_ORG_IDS, SKIP_SLUG_PREFIXES
    U = get_user_model()
    out = {}
    for u in U._base_manager.filter(is_active=True).exclude(email='').select_related('organization'):
        org = getattr(u, 'organization', None)
        if not org or org.id in SKIP_ORG_IDS:
            continue
        if any((org.slug or '').startswith(p) for p in SKIP_SLUG_PREFIXES):
            continue
        out[u.email.strip().lower()] = org
    return out


def fetch_replies():
    """Повертає список листів від відомих клінік: [{org, from, subject, body, ...}]."""
    senders = known_senders()
    if not senders:
        return []

    since = (timezone.now() - timezone.timedelta(days=LOOKBACK_DAYS)).strftime('%d-%b-%Y')
    found = []
    M = imaplib.IMAP4_SSL(settings.EMAIL_HOST, IMAP_PORT, timeout=30)
    try:
        M.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        M.select('INBOX')
        code, data = M.search(None, f'(SINCE {since})')
        for num in data[0].split():
            code, d = M.fetch(num, '(BODY.PEEK[])')
            if not d or not d[0]:
                continue
            msg = email.message_from_bytes(d[0][1])
            addr = parseaddr(msg.get('From', ''))[1].strip().lower()
            org = senders.get(addr)
            if not org:
                continue                            # не наш клієнт — не існує
            found.append({
                'org': org,
                'from': addr,
                'name': _decode(msg.get('From', '')).split('<')[0].strip(' "'),
                'subject': _decode(msg.get('Subject', '')),
                'body': _plain_body(msg),
                'message_id': msg.get('Message-ID', ''),
                'references': msg.get('References', ''),
                'date': msg.get('Date', ''),
            })
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return found


def save_draft(*, to_addr, subject, body, in_reply_to='', references=''):
    """Кладе готову відповідь у Чернетки — щоб Олег відкрив пошту і відправив."""
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['From'] = settings.DEFAULT_FROM_EMAIL
    msg['To'] = to_addr
    msg['Subject'] = subject if subject.lower().startswith('re:') else f'Re: {subject}'
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain='kizuna.com.ua')
    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
        msg['References'] = (references + ' ' + in_reply_to).strip()

    M = imaplib.IMAP4_SSL(settings.EMAIL_HOST, IMAP_PORT, timeout=30)
    try:
        M.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        M.append(DRAFTS, '\\Draft', imaplib.Time2Internaldate(time.time()),
                 msg.as_bytes())
        return True
    finally:
        try:
            M.logout()
        except Exception:
            pass
