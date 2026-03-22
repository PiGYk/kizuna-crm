from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    return render(request, 'dashboard.html')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', dashboard, name='dashboard'),
    path('', include('apps.accounts.urls')),
    path('clients/', include('apps.clients.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('services/', include('apps.services.urls')),
    path('billing/', include('apps.billing.urls')),
    path('health/', lambda r: HttpResponse('ok')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
