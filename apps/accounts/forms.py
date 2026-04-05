from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.text import slugify
from .models import User

_input_cls = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand-gold focus:border-transparent bg-white'
)


class ClinicRegistrationForm(forms.Form):
    clinic_name = forms.CharField(
        label='Назва клініки',
        max_length=200,
        widget=forms.TextInput(attrs={'class': _input_cls, 'placeholder': 'Ветеринарна клініка «Барсик»'}),
    )
    first_name = forms.CharField(
        label='Ваше ім\'я',
        max_length=150,
        widget=forms.TextInput(attrs={'class': _input_cls}),
    )
    last_name = forms.CharField(
        label='Прізвище',
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'class': _input_cls}),
    )
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'class': _input_cls}),
    )
    username = forms.CharField(
        label='Логін',
        max_length=150,
        widget=forms.TextInput(attrs={'class': _input_cls, 'autocomplete': 'off'}),
    )
    password1 = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={'class': _input_cls}),
    )
    password2 = forms.CharField(
        label='Повторити пароль',
        widget=forms.PasswordInput(attrs={'class': _input_cls}),
    )

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Цей логін вже зайнятий.')
        return username

    def clean(self):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        cd = super().clean()
        p1 = cd.get('password1')
        p2 = cd.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', 'Паролі не збігаються.')
        if p1:
            try:
                validate_password(p1)
            except DjangoValidationError as e:
                self.add_error('password1', e)
        return cd

    def _unique_slug(self, base):
        from apps.clinic.models import Organization
        import re
        slug = slugify(base, allow_unicode=False) or 'clinic'
        slug = re.sub(r'[^a-z0-9-]', '', slug)[:40] or 'clinic'
        candidate, n = slug, 1
        while Organization.objects.filter(slug=candidate).exists():
            candidate = f'{slug}-{n}'
            n += 1
        return candidate

    def save(self):
        from apps.clinic.models import Organization
        from django.utils import timezone
        from datetime import timedelta
        cd = self.cleaned_data
        org = Organization.objects.create(
            name=cd['clinic_name'],
            slug=self._unique_slug(cd['clinic_name']),
            trial_expires_at=timezone.now() + timedelta(days=14),
        )
        user = User(
            username=cd['username'],
            first_name=cd['first_name'],
            last_name=cd.get('last_name', ''),
            email=cd['email'],
            role=User.Role.ADMIN,
            organization=org,
            is_active=False,  # активується після підтвердження email
        )
        user.set_password(cd['password1'])
        user.save()
        return user


class UserCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'role', 'is_active')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
                'focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent'
            )


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'role', 'is_active')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = (
                'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
                'focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent'
            )


class PasswordChangeForm(forms.Form):
    password1 = forms.CharField(
        label='Новий пароль',
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'
        })
    )
    password2 = forms.CharField(
        label='Повторити пароль',
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500'
        })
    )

    def clean(self):
        cd = super().clean()
        if cd.get('password1') != cd.get('password2'):
            raise forms.ValidationError('Паролі не збігаються')
        return cd
