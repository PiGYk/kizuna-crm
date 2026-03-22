from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView

from .forms import UserCreateForm, UserUpdateForm, PasswordChangeForm
from .mixins import AdminRequiredMixin
from .models import User


class UserListView(AdminRequiredMixin, ListView):
    model = User
    template_name = 'accounts/users.html'
    context_object_name = 'users'
    ordering = ('last_name', 'first_name')


class UserCreateView(AdminRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:users')

    def form_valid(self, form):
        messages.success(self.request, 'Користувача створено')
        return super().form_valid(form)


class UserUpdateView(AdminRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'accounts/user_form.html'
    success_url = reverse_lazy('accounts:users')

    def form_valid(self, form):
        messages.success(self.request, 'Збережено')
        return super().form_valid(form)


def user_set_password(request, pk):
    if not request.user.is_admin():
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    user = get_object_or_404(User, pk=pk)
    form = PasswordChangeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user.set_password(form.cleaned_data['password1'])
        user.save()
        messages.success(request, f'Пароль для {user.username} змінено')
        return redirect('accounts:users')
    return render(request, 'accounts/set_password.html', {'form': form, 'target_user': user})
