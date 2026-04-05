from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView

from django.contrib.auth.decorators import login_required

from .forms import UserCreateForm, UserUpdateForm, PasswordChangeForm, ClinicRegistrationForm
from .mixins import AdminRequiredMixin
from .models import User, EmailVerification


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
        return User.objects.filter(organization=self.request.organization)


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
                current = User.objects.filter(organization=org).count()
                if current >= limit:
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
        messages.success(self.request, 'Збережено')
        return super().form_valid(form)


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
        messages.success(request, f'Пароль для {user.username} змінено')
        return redirect('accounts:users')
    return render(request, 'accounts/set_password.html', {'form': form, 'target_user': user})


def register(request):
    """Публічна реєстрація нової клініки + адміна."""
    if request.user.is_authenticated:
        return redirect('dashboard')

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
            return render(request, 'accounts/register.html', {'form': form})

        return render(request, 'accounts/register_pending.html', {'email': user.email})

    return render(request, 'accounts/register.html', {'form': form})


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

    email = request.POST.get('email', '').strip()
    try:
        user = User.objects.get(email=email, is_active=False)
        verification = EmailVerification.create_for(user)
        _send_verification_email(request, user, verification)
        messages.success(request, 'Лист надіслано повторно.')
    except User.DoesNotExist:
        # Не розкриваємо чи існує email
        messages.success(request, 'Якщо email знайдено — лист надіслано.')

    return render(request, 'accounts/register_pending.html', {'email': email, 'resent': True})
