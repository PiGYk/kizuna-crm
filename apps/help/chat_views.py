# -*- coding: utf-8 -*-
"""Обробники чат-помічника: повідомлення і залишений контакт."""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.clinic.demo_guard import has_profanity

from . import chat

_JOKE = "Без лайки, будь ласка 🙂 Питайте по суті — з радістю допоможу."
_TOO_LONG = "Питання задовге — сформулюйте коротше, будь ласка (до 600 знаків)."


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "0.0.0.0")[:45]


def _body(request):
    try:
        return json.loads((request.body or b"{}").decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


@csrf_exempt
@require_POST
def chat_message(request):
    if not chat.enabled():
        return JsonResponse({"ok": False, "reply": "Помічник тимчасово вимкнений."})

    data = _body(request)
    question = str(data.get("message", "")).strip()
    history = data.get("history") or []
    if not isinstance(history, list):
        history = []

    if not question:
        return JsonResponse({"ok": True, "reply": chat.greeting(), "sources": []})
    if len(question) > chat.MAX_MESSAGE_LEN:
        return JsonResponse({"ok": True, "reply": _TOO_LONG, "sources": []})
    if has_profanity(question):
        return JsonResponse({"ok": True, "reply": _JOKE, "sources": []})

    ip = _client_ip(request)
    stop = chat.check_limits(ip, data.get("conv_id", ""), len(history))
    if stop:
        return JsonResponse({"ok": True, "reply": stop, "sources": [], "offer_lead": True})

    try:
        answer, sources = chat.ask(question, history)
    except Exception:
        return JsonResponse({
            "ok": True,
            "reply": ("Щось не зв'язалось із помічником. Спробуйте ще раз за хвилину,"
                      " або лишіть контакт — власник відповість особисто."),
            "sources": [],
            "offer_lead": True,
        })
    return JsonResponse({"ok": True, "reply": answer, "sources": sources})


@csrf_exempt
@require_POST
def chat_lead(request):
    """Контакт із чату — у ту саму скриньку заявок, що й форма лендінга."""
    from apps.clinic.models import ContactLead

    data = _body(request)
    if str(data.get("website", "")).strip():        # пастка для роботів
        return JsonResponse({"ok": True})

    name = str(data.get("name", "")).strip()[:120]
    phone = str(data.get("phone", "")).strip()[:20]
    email = str(data.get("email", "")).strip()[:254]
    if not phone:
        return JsonResponse({"ok": False, "error": "Вкажіть, будь ласка, телефон."})
    if has_profanity(name):
        return JsonResponse({"ok": False, "error": "Вкажіть, будь ласка, справжнє імʼя."})

    ip = _client_ip(request)
    if chat._bump("kzchat:lead:%s" % ip, 3600) > 3:
        return JsonResponse({"ok": False, "error": "Заявку вже прийнято, дякуємо."})

    lines = []
    for turn in (data.get("history") or [])[-20:]:
        who = "Відвідувач" if turn.get("role") != "assistant" else "Помічник"
        text = str(turn.get("text", ""))[:600]
        if text:
            lines.append("%s: %s" % (who, text))
    transcript = "\n".join(lines)[:6000]

    ContactLead.objects.create(
        name=name or "З чату",
        phone=phone,
        email=email,
        message="ЗАЯВКА З ЧАТ-ПОМІЧНИКА\n\n%s" % (transcript or "(розмови не було)"),
        ip=ip if ip != "0.0.0.0" else None,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        utm_source=str(data.get("utm_source", ""))[:120],
        utm_medium=str(data.get("utm_medium", ""))[:120],
        utm_campaign=str(data.get("utm_campaign", ""))[:120],
        referer=str(data.get("referer", ""))[:500],
    )
    return JsonResponse({"ok": True})
