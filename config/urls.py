from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.clients.urls')),
    path('', include('apps.accounts.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('services/', include('apps.services.urls')),
    path('billing/', include('apps.billing.urls')),
    path('health/', lambda r: HttpResponse('ok')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
