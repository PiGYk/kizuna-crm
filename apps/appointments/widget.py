"""Вставний віджет «Запис на прийом» для сайту клініки.

Клініка вставляє на свою сторінку два рядки:

    <div id="vetcrm-booking"></div>
    <script src="https://<crm>/api/public/widget.js?org=<slug>"></script>

Чому віддаємо JS з view, а не файлом у static:
  * підставляємо назву й фірмовий колір конкретної клініки;
  * адреса CRM береться з самого запиту — не треба нічого прописувати руками;
  * не залежимо від collectstatic на кожній інсталяції.

Розмітка віджета живе у Shadow DOM: стилі сайту клініки не ламають форму,
а стилі форми не течуть на сайт.
"""
import json

from django.http import HttpResponse, HttpResponseNotFound
from django.views.decorators.cache import cache_control

_WIDGET_JS = r"""
(function () {
  'use strict';
  var CFG = __CONFIG__;

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else { fn(); }
  }

  var CSS = [
    ':host{all:initial;}',
    '*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}',
    '.wrap{max-width:520px;background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:24px;color:#111827;}',
    '.title{font-size:20px;font-weight:700;margin:0 0 4px;}',
    '.sub{font-size:14px;color:#6b7280;margin:0 0 20px;}',
    '.row{margin-bottom:14px;}',
    '.row2{display:flex;gap:12px;}',
    '.row2>div{flex:1;min-width:0;}',
    'label{display:block;font-size:13px;font-weight:600;margin-bottom:6px;color:#374151;}',
    'input,select,textarea{width:100%;padding:10px 12px;border:1px solid #d1d5db;border-radius:10px;',
    'font-size:14px;background:#fff;color:#111827;outline:none;}',
    'input:focus,select:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(0,0,0,.06);}',
    'textarea{resize:vertical;min-height:64px;}',
    '.slots{display:flex;flex-wrap:wrap;gap:8px;}',
    '.slot{padding:8px 12px;border:1px solid #d1d5db;border-radius:999px;font-size:13px;cursor:pointer;background:#fff;}',
    '.slot:hover{border-color:var(--accent);}',
    '.slot.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600;}',
    '.hint{font-size:13px;color:#6b7280;padding:6px 0;}',
    'button.send{width:100%;padding:13px;border:0;border-radius:10px;background:var(--accent);color:#fff;',
    'font-size:15px;font-weight:700;cursor:pointer;margin-top:6px;}',
    'button.send:disabled{opacity:.55;cursor:default;}',
    '.err{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;border-radius:10px;padding:10px 12px;font-size:13px;margin-bottom:14px;}',
    '.ok{text-align:center;padding:28px 8px;}',
    '.ok .ico{font-size:44px;line-height:1;}',
    '.ok h3{font-size:19px;margin:14px 0 6px;}',
    '.ok p{font-size:14px;color:#6b7280;margin:0;}',
    '.req{color:#dc2626;}'
  ].join('');

  function h(tag, attrs, html) {
    var el = document.createElement(tag);
    if (attrs) { for (var k in attrs) { el.setAttribute(k, attrs[k]); } }
    if (html != null) { el.innerHTML = html; }
    return el;
  }

  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function isoDate(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function mount(host) {
    var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
    var style = document.createElement('style');
    style.textContent = ':host{--accent:' + CFG.accent + ';}' + CSS;
    root.appendChild(style);

    var wrap = h('div', { class: 'wrap' });
    wrap.style.setProperty('--accent', CFG.accent);
    root.appendChild(wrap);

    var chosenTime = null;

    function renderForm() {
      chosenTime = null;
      wrap.innerHTML = '';
      wrap.appendChild(h('h2', { class: 'title' }, CFG.title));
      wrap.appendChild(h('p', { class: 'sub' }, CFG.subtitle));

      var errBox = h('div', { class: 'err', style: 'display:none' });
      wrap.appendChild(errBox);

      var form = h('form');

      var r1 = h('div', { class: 'row' });
      r1.appendChild(h('label', null, "Ваше ім'я <span class='req'>*</span>"));
      var iName = h('input', { type: 'text', name: 'name', required: 'required', autocomplete: 'name' });
      r1.appendChild(iName);
      form.appendChild(r1);

      var r2 = h('div', { class: 'row' });
      r2.appendChild(h('label', null, "Телефон <span class='req'>*</span>"));
      var iPhone = h('input', { type: 'tel', name: 'phone', required: 'required',
                                placeholder: '+38 (0__) ___-__-__', autocomplete: 'tel' });
      r2.appendChild(iPhone);
      form.appendChild(r2);

      var r3 = h('div', { class: 'row row2' });
      var c1 = h('div');
      c1.appendChild(h('label', null, 'Кличка тварини'));
      var iPet = h('input', { type: 'text', name: 'pet_name' });
      c1.appendChild(iPet);
      var c2 = h('div');
      c2.appendChild(h('label', null, 'Вид'));
      var iType = h('select', { name: 'pet_type' });
      ['', 'Собака', 'Кіт', 'Гризун', 'Птах', 'Інше'].forEach(function (v) {
        iType.appendChild(h('option', { value: v }, v || '— оберіть —'));
      });
      c2.appendChild(iType);
      r3.appendChild(c1); r3.appendChild(c2);
      form.appendChild(r3);

      var r4 = h('div', { class: 'row' });
      r4.appendChild(h('label', null, 'Причина звернення'));
      var iService = h('input', { type: 'text', name: 'service',
                                  placeholder: 'Огляд, щеплення, консультація…' });
      r4.appendChild(iService);
      form.appendChild(r4);

      var r5 = h('div', { class: 'row' });
      r5.appendChild(h('label', null, 'Бажана дата'));
      var today = new Date();
      var iDate = h('input', { type: 'date', name: 'date', min: isoDate(today) });
      r5.appendChild(iDate);
      form.appendChild(r5);

      var r6 = h('div', { class: 'row', style: 'display:none' });
      r6.appendChild(h('label', null, 'Вільний час'));
      var slotBox = h('div', { class: 'slots' });
      r6.appendChild(slotBox);
      form.appendChild(r6);

      var r7 = h('div', { class: 'row' });
      r7.appendChild(h('label', null, 'Коментар'));
      var iNotes = h('textarea', { name: 'notes' });
      r7.appendChild(iNotes);
      form.appendChild(r7);

      var btn = h('button', { class: 'send', type: 'submit' }, 'Записатися');
      form.appendChild(btn);
      wrap.appendChild(form);

      function showErr(msg) {
        errBox.textContent = msg;
        errBox.style.display = msg ? 'block' : 'none';
      }

      iDate.addEventListener('change', function () {
        chosenTime = null;
        slotBox.innerHTML = '';
        if (!iDate.value) { r6.style.display = 'none'; return; }
        r6.style.display = 'block';
        slotBox.appendChild(h('div', { class: 'hint' }, 'Шукаю вільний час…'));
        fetch(CFG.base + '/api/public/slots/?org=' + encodeURIComponent(CFG.org) +
              '&date=' + encodeURIComponent(iDate.value))
          .then(function (r) { return r.json(); })
          .then(function (data) {
            slotBox.innerHTML = '';
            if (data.day_off) {
              slotBox.appendChild(h('div', { class: 'hint' }, 'Цього дня клініка не працює — оберіть іншу дату.'));
              return;
            }
            var list = data.slots || [];
            if (!list.length) {
              slotBox.appendChild(h('div', { class: 'hint' }, 'На цю дату вільного часу немає. Оберіть іншу — або надішліть заявку без часу, ми передзвонимо.'));
              return;
            }
            list.forEach(function (t) {
              var b = h('button', { class: 'slot', type: 'button' }, t);
              b.addEventListener('click', function () {
                chosenTime = (chosenTime === t) ? null : t;
                Array.prototype.forEach.call(slotBox.children, function (x) {
                  x.classList.remove('on');
                });
                if (chosenTime) { b.classList.add('on'); }
              });
              slotBox.appendChild(b);
            });
          })
          .catch(function () {
            slotBox.innerHTML = '';
            slotBox.appendChild(h('div', { class: 'hint' }, 'Не вдалося завантажити вільний час. Заявку все одно можна надіслати.'));
          });
      });

      form.addEventListener('submit', function (e) {
        e.preventDefault();
        showErr('');
        var name = iName.value.trim();
        var phone = iPhone.value.trim();
        if (!name) { showErr("Вкажіть, будь ласка, ваше ім'я."); iName.focus(); return; }
        if (phone.replace(/\D/g, '').length < 9) {
          showErr('Вкажіть, будь ласка, коректний номер телефону.'); iPhone.focus(); return;
        }
        btn.disabled = true;
        btn.textContent = 'Надсилаю…';

        fetch(CFG.base + '/api/public/lead/?org=' + encodeURIComponent(CFG.org), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            org: CFG.org,
            name: name,
            phone: phone,
            pet_name: iPet.value.trim(),
            pet_type: iType.value,
            service: iService.value.trim(),
            date: iDate.value || '',
            time: chosenTime || '',
            notes: iNotes.value.trim(),
            source: CFG.source
          })
        })
          .then(function (r) {
            return r.json().then(function (body) { return { ok: r.ok, status: r.status, body: body }; });
          })
          .then(function (res) {
            if (res.ok) { renderDone(); return; }
            if (res.status === 429) {
              showErr('Забагато спроб поспіль. Зачекайте хвилину і спробуйте ще раз.');
            } else {
              showErr((res.body && res.body.error) || 'Не вдалося надіслати заявку. Спробуйте ще раз або зателефонуйте нам.');
            }
            btn.disabled = false;
            btn.textContent = 'Записатися';
          })
          .catch(function () {
            showErr("Немає зв'язку з клінікою. Перевірте інтернет і спробуйте ще раз.");
            btn.disabled = false;
            btn.textContent = 'Записатися';
          });
      });
    }

    function renderDone() {
      wrap.innerHTML = '';
      var ok = h('div', { class: 'ok' });
      ok.appendChild(h('div', { class: 'ico' }, '✅'));
      ok.appendChild(h('h3', null, 'Заявку прийнято'));
      ok.appendChild(h('p', null, "Ми зв'яжемося з вами найближчим часом, щоб підтвердити запис."));
      var again = h('button', { class: 'send', type: 'button', style: 'margin-top:20px' }, 'Записати ще одну тварину');
      again.addEventListener('click', renderForm);
      ok.appendChild(again);
      wrap.appendChild(ok);
    }

    renderForm();
  }

  ready(function () {
    var host = document.getElementById(CFG.mount_id);
    if (!host) {
      // Контейнера немає — вставляємо одразу після тега <script>.
      var s = document.currentScript || (function () {
        var all = document.getElementsByTagName('script');
        return all[all.length - 1];
      })();
      host = document.createElement('div');
      host.id = CFG.mount_id;
      if (s && s.parentNode) { s.parentNode.insertBefore(host, s.nextSibling); }
      else { document.body.appendChild(host); }
    }
    if (host.getAttribute('data-vetcrm-ready') === '1') { return; }
    host.setAttribute('data-vetcrm-ready', '1');
    mount(host);
  });
})();
"""

MOUNT_ID = 'vetcrm-booking'


@cache_control(max_age=300, public=True)
def widget_js(request):
    """GET /api/public/widget.js?org=<slug> — віддає готовий віджет форми."""
    from apps.clinic.models import Organization

    slug = (request.GET.get('org') or '').strip()
    if not slug:
        return HttpResponse(
            "console.error('[vetcrm] У тезі <script> не вказано ?org=<ідентифікатор клініки>');",
            content_type='application/javascript; charset=utf-8',
        )
    try:
        org = Organization.objects.get(slug=slug, is_active=True)
    except Organization.DoesNotExist:
        return HttpResponseNotFound(
            "console.error('[vetcrm] Клініку не знайдено — перевірте параметр org');",
            content_type='application/javascript; charset=utf-8',
        )

    accent = (org.primary_color or '#DEAA01').strip()
    if not accent.startswith('#') or len(accent) not in (4, 7):
        accent = '#DEAA01'

    config = {
        'org': org.slug,
        'base': request.build_absolute_uri('/').rstrip('/'),
        'accent': accent,
        'title': 'Запис на прийом',
        'subtitle': f'{org.short_name or org.name} — залиште заявку, ми підтвердимо запис.',
        'mount_id': MOUNT_ID,
        'source': f'{org.slug}-website',
    }

    body = _WIDGET_JS.replace('__CONFIG__', json.dumps(config, ensure_ascii=False))
    return HttpResponse(body, content_type='application/javascript; charset=utf-8')
