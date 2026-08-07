"""UI-сторінка для генерації CardDAV токена.

URL: /carddav-setup/
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import CardDAVToken


@login_required
def setup_page(request):
    cdt = CardDAVToken.get_or_create_for(request.user)
    base = request.build_absolute_uri('/').rstrip('/')
    carddav_url = f'{base}/carddav/{request.user.username}/'
    return render(request, 'carddav/setup.html', {
        'cdt': cdt,
        'carddav_url': carddav_url,
        'username': request.user.username,
        'host': request.get_host(),
    })


@login_required
@require_POST
def regenerate_token(request):
    cdt = CardDAVToken.get_or_create_for(request.user)
    cdt.regenerate()
    messages.success(request, 'Новий токен згенеровано. Старий більше не працює.')
    return redirect('carddav_setup')
