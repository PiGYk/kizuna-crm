import logging
import time

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import UserCreateForm, UserUpdateForm, PasswordChangeForm, ClinicRegistrationForm
from .mixins import AdminRequiredMixin
from .models import User, EmailVerification
from .staff import fired_users, seats_left, user_history

logger = logging.getLogger(__name__)


# ── Захист реєстрації від ботів (31.10.2026) ───────────────────────────────
# З 15.10 боти створювали 3–11 «клінік» на день (102 за два тижні), назва —
# 10 випадкових літер, пошта — чужа справжня (gmail, hotmail, університети).
# Кожна така реєстрація змушувала нашу пошту слати лист підтвердження
# незнайомій людині: класичне «підписне бомбардування», яке б'є по репутації
# домену, з якого йдуть листи клієнтам.
_REG_SALT = 'kizuna.register.v1'
_REG_MIN_SECONDS = 3          # людина не заповнить шість полів швидше
_REG_MAX_AGE = 3 * 3600       # довше — сторінка застаріла, просимо ще раз
_HONEYPOT = 'kz_hp'           # невидиме поле: людина його не бачить, бот заповнює


def _client_ip(request):
    """Справжня адреса клієнта. nginx ставить X-Real-IP = $remote_addr і перезаписує
    те, що прислав клієнт; X-Forwarded-For він лише ДОПИСУЄ, тож перший елемент
    там підставляє будь-хто — ліміт за ним обходився."""
    return (request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR') or '0.0.0.0').strip()


def _over_limit(key, limit, window):
    """Фіксоване вікно в кеші: True — цей запит уже понад ліміт."""
    cache.add(key, 0, timeout=window)
    try:
        n = cache.incr(key)
    except ValueError:  # ключ протух між add і incr
        cache.set(key, 1, timeout=window)
        n = 1
    return n > limit


def _register_token():
    return signing.dumps(int(time.time()), salt=_REG_SALT)


def _register_verdict(request):
    """None — схоже на людину; 'bot' — тихо відмовити; 'stale'/'nojs' — попросити ще раз."""
    if (request.POST.get(_HONEYPOT) or '').strip():
        return 'bot'
    raw = request.POST.get('form_ts', '')
    if not raw:
        return 'nojs'  # токен ставить JS при надсиланні; без нього — бот або вимкнений JS
    try:
        started = int(signing.loads(raw, salt=_REG_SALT, max_age=_REG_MAX_AGE))
    except signing.SignatureExpired:
        return 'stale'
    except (signing.BadSignature, ValueError, TypeError):
        return 'bot'
    if time.time() - started < _REG_MIN_SECONDS:
        return 'bot'
    return None


def _send_verification_email(request, user: User, verification: EmailVerification):
    verify_url = request.build_absolute_uri(
        reverse_lazy('accounts:verify_email', kwargs={'token': verification.token})
    )
    subject = f'Активація акаунту Kizuna CRM для {user.first_name or user.username}'
    html_body = render_to_string('email/verification.html', {
        'user': user,
        'verify_url': verify_url,
        'ttl_hours': EmailVerification.TOKEN_TTL_HOURS,
    })
    text_body = (
        f'Вітаємо, {user.first_name or user.username}!\n\n'
        f'Для завершення реєстрації в Kizuna CRM перейдіть за посиланням:\n{verify_url}\n\n'
        f'Посилання дійсне {EmailVerification.TOKEN_TTL_HOURS} годин.\n\n'
        f'Якщо ви не реєструвались — проігноруйте цей лист.'
    )
    send_mail(
        subject=subject,
        message=text_body,
        from_email=None,  # DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
        html_message=html_body,
        fail_silently=False,
    )


class UserListView(AdminRequiredMixin, ListView):
    model = User
    template_name = 'accounts/users.html'
    context_object_name = 'users'
    ordering = ('last_name', 'first_name')

    def get_queryset(self):
        # Звільнені — окремим згорнутим списком під таблицею (ANVAR 01.11)
        return User.objects.filter(organization=self.request.organization, is_active=True).order_by(*self.ordering)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['fired'] = fired_users(self.request.organization)
        return ctx


class UserCreateView(AdminRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:users')

    def dispatch(self, request, *args, **kwargs):
        org = request.organization
        if org and not request.user.is_superuser:
            limit = org.max_doctors
            if limit is not None:
                # місце в тарифі займають лише активні — звільнені ні
                if seats_left(org) <= 0:
                    messages.error(
                        request,
                        f'Ваш тариф «{org.get_plan_display() or "Старт"}» дозволяє максимум '
                        f'{limit} користувачів. Перейдіть на вищий тариф щоб додати більше.',
                    )
                    return redirect(self.success_url)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save(commit=False)
        user.organization = self.request.organization
        user.save()
        messages.success(self.request, 'Користувача створено')
        return redirect(self.success_url)


class UserUpdateView(AdminRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:users')

    def get_queryset(self):
        return User.objects.filter(organization=self.request.organization)

    def form_valid(self, form):
        # Захист від самоблокування (ANVAR.VET 30.10.2026: єдиний адмін зняв собі «Активний»).
        if form.instance.pk == self.request.user.pk:
            if not form.cleaned_data.get('is_active', True):
                form.add_error('is_active', 'Не можна деактивувати власний акаунт.')
                return self.form_invalid(form)
            if form.cleaned_data.get('role') != User.Role.ADMIN:
                form.add_error('role', 'Не можна зняти з себе роль адміністратора.')
                return self.form_invalid(form)
        # повернення звільненого галочкою «Активний» — теж у межах тарифу
        org = self.request.organization
        was_active = User.objects.filter(pk=form.instance.pk).values_list('is_active', flat=True).first()
        left = seats_left(org) if org and not self.request.user.is_superuser else None
        if form.cleaned_data.get('is_active') and not was_active and left is not None and left <= 0:
            form.add_error('is_active', f'Тариф дозволяє {org.max_doctors} активних користувачів — місць нема.')
            return self.form_invalid(form)
        messages.success(self.request, 'Збережено')
        return super().form_valid(form)


def _back(request):
    nxt = request.POST.get('next', '')
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(nxt)
    return redirect('accounts:users')


def _name(u):
    return u.get_full_name() or u.username


@login_required
@require_POST
def user_dismiss(request, pk):
    """«Звільнити»: не входить, зникає з вибору лікаря/виконавця й зі списку команди,
    звільняє місце в тарифі; прийоми й рахунки з його ім'ям лишаються."""
    if not request.user.is_admin():
        raise PermissionDenied
    org = request.organization
    user = get_object_or_404(User, pk=pk, organization=org, is_active=True)
    if user.pk == request.user.pk or user.is_superuser:
        messages.error(request, 'Цього користувача звільнити не можна.')
        return _back(request)
    if user.is_admin() and not User.objects.filter(
            organization=org, role=User.Role.ADMIN, is_active=True).exclude(pk=user.pk).exists():
        messages.error(request, 'Це єдиний адміністратор клініки — спершу призначте іншого.')
        return _back(request)
    user.is_active = False
    user.save(update_fields=['is_active'])
    note = ''
    if org.default_doctor_id == user.pk:
        org.default_doctor = None
        org.save(update_fields=['default_doctor'])
        note = ' Він був лікарем за замовчуванням — оберіть іншого в налаштуваннях.'
    messages.success(request, f'{_name(user)} звільнено: не входить у CRM і не пропонується у виборі лікаря чи виконавця. '
                              f'Прийоми й рахунки з його ім\'ям лишаються.{note}')
    return _back(request)


@login_required
@require_POST
def user_restore(request, pk):
    if not request.user.is_admin():
        raise PermissionDenied
    org = request.organization
    user = get_object_or_404(User, pk=pk, organization=org, is_active=False)
    left = seats_left(org)
    if left is not None and left <= 0 and not request.user.is_superuser:
        messages.error(request, f'Тариф дозволяє {org.max_doctors} активних користувачів — спершу звільніть когось або перейдіть на вищий тариф.')
        return _back(request)
    user.is_active = True
    user.save(update_fields=['is_active'])
    messages.success(request, f'{_name(user)} знову в команді.')
    return _back(request)


@login_required
@require_POST
def user_delete(request, pk):
    """Назавжди — лише звільненого й лише без історії (створений помилково). Інакше каскад
    знищив би його зміни й зарплати, а в прийомах і рахунках лікар став би порожнім."""
    if not request.user.is_admin():
        raise PermissionDenied
    user = get_object_or_404(User, pk=pk, organization=request.organization, is_active=False)
    if user.pk == request.user.pk or user.is_superuser:
        messages.error(request, 'Цього користувача видалити не можна.')
        return _back(request)
    history = user_history(user)
    if history:
        what = ', '.join(f'{name.lower()} {n}' for name, n in history[:3])
        messages.error(request, f'{_name(user)} не видалити: за ним історія ({what}). Звільнений нікому не заважає — '
                                f'не входить і не показується у виборі лікаря чи виконавця.')
        return _back(request)
    name = _name(user)
    user.delete()
    messages.success(request, f'{name} видалено назавжди.')
    return _back(request)


@login_required
def user_set_password(request, pk):
    if not request.user.is_admin():
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    user = get_object_or_404(User, pk=pk, organization=request.organization)
    form = PasswordChangeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user.set_password(form.cleaned_data['password1'])
        user.save()
        if user.pk == request.user.pk:
            # Свій пароль: без цього Django викидає адміна з усіх сесій, і поточної теж.
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, user)
        messages.success(request, f'Пароль для {user.username} змінено')
        return redirect('accounts:users')
    return render(request, 'accounts/set_password.html', {'form': form, 'target_user': user})


def register(request):
    """Публічна реєстрація нової клініки + адміна."""
    if request.user.is_authenticated:
        return redirect('dashboard')

    # Ліміти на POST: з однієї адреси — 6 спроб на годину (людині з помилками
    # в паролі вистачить), на всіх разом — 30 реєстрацій, що пройшли перевірку
    # на бота, на годину (запобіжник від розподіленого напливу).
    if request.method == 'POST':
        ip = _client_ip(request)
        if _over_limit(f'register-rl:{ip}', 6, 3600):
            return HttpResponse(
                'Забагато спроб реєстрації. Спробуйте через годину.',
                status=429,
            )
        verdict = _register_verdict(request)
        if verdict == 'bot':
            # Боту — та сама сторінка «перевірте пошту», щоб не вчився обходити.
            # Нічого не створюємо і жодного листа не шлемо.
            logger.warning('register: відсічено бота ip=%s', ip)
            return render(request, 'accounts/register_pending.html',
                          {'email': (request.POST.get('email') or '')[:254]})
        if verdict in ('stale', 'nojs'):
            form = ClinicRegistrationForm(request.POST)
            form.is_valid()
            form.add_error(None, 'Сторінка застаріла — натисніть «Зареєструватися» ще раз.'
                           if verdict == 'stale' else
                           'Не вдалося надіслати форму. Оновіть сторінку й спробуйте ще раз '
                           '(потрібен увімкнений JavaScript).')
            return render(request, 'accounts/register.html', {'form': form, 'form_ts': _register_token()})
        if _over_limit('register-rl:all', 30, 3600):
            logger.error('register: понад 30 реєстрацій за годину — пауза')
            return HttpResponse('Реєстрація тимчасово призупинена. Спробуйте за годину.', status=429)

    form = ClinicRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()  # is_active=False
        verification = EmailVerification.create_for(user)
        try:
            _send_verification_email(request, user, verification)
        except Exception:
            # Якщо пошта не надіслалась — видаляємо юзера і показуємо помилку
            user.organization.delete()
            user.delete()
            messages.error(request, 'Не вдалось надіслати лист верифікації. Спробуйте пізніше або зверніться в підтримку.')
            return render(request, 'accounts/register.html', {'form': form, 'form_ts': _register_token()})

        return render(request, 'accounts/register_pending.html', {'email': user.email})

    return render(request, 'accounts/register.html', {'form': form, 'form_ts': _register_token()})


def verify_email(request, token: str):
    """Підтвердження email за токеном."""
    try:
        verification = EmailVerification.objects.select_related('user').get(token=token)
    except EmailVerification.DoesNotExist:
        return render(request, 'accounts/verify_invalid.html', {'reason': 'not_found'})

    if verification.is_expired():
        # Видаляємо запис, щоб можна було повторно надіслати
        verification.delete()
        return render(request, 'accounts/verify_invalid.html', {'reason': 'expired'})

    user = verification.user
    user.is_active = True
    user.save(update_fields=['is_active'])
    verification.delete()

    auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, f'Email підтверджено! Ласкаво просимо до Kizuna CRM, {user.first_name or user.username}!')
    return redirect('dashboard')


def resend_verification(request):
    """Повторна відправка листа верифікації."""
    if request.method != 'POST':
        return redirect('accounts:register')

    email = request.POST.get('email', '').strip()[:254]
    # Без лімітів ця кнопка дозволяла будь-кому змусити нашу пошту слати листи
    # на будь-яку непідтверджену адресу скільки завгодно разів.
    ip = _client_ip(request)
    limited = _over_limit(f'resend-rl:ip:{ip}', 5, 3600) or (
        bool(email) and _over_limit(f'resend-rl:em:{email.lower()}', 3, 86400))
    user = None
    if email and not limited:
        # Боти реєстрували одну адресу кілька разів — get() падав би з 500.
        user = (User.objects.filter(email__iexact=email, is_active=False)
                .order_by('-date_joined').first())
    if user:
        verification = EmailVerification.create_for(user)
        try:
            _send_verification_email(request, user, verification)
        except Exception:
            logger.exception('resend_verification: лист не пішов')
    elif limited:
        logger.warning('resend_verification: ліміт ip=%s', ip)
    # Однакова відповідь у всіх випадках: не розкриваємо, чи існує адреса.
    messages.success(request, 'Якщо адресу знайдено — лист надіслано.')

    return render(request, 'accounts/register_pending.html', {'email': email, 'resent': True})
