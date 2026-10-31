"""Бланки згод: меню (вибір тварини й бланка) і аркуш A4 для друку."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .consents import CONSENTS, CONSENTS_BY_KEY
from .models import Patient

BLANK = '____________________'


@login_required
def consent_menu(request):
    q = (request.GET.get('q') or '').strip()
    patient = None
    if request.GET.get('patient', '').isdigit():
        patient = get_object_or_404(Patient.objects.select_related('client'), pk=int(request.GET['patient']))
    results = []
    if q and patient is None:
        results = (Patient.objects.filter(is_archived=False)
                   .filter(Q(name__icontains=q) | Q(client__last_name__icontains=q)
                           | Q(client__first_name__icontains=q) | Q(client__phone__icontains=q))
                   .select_related('client').order_by('name')[:30])
    return render(request, 'clients/consents/menu.html', {
        'consents': CONSENTS, 'q': q, 'results': results, 'patient': patient,
    })


@login_required
def consent_print(request, key, patient_pk=None):
    meta = CONSENTS_BY_KEY.get(key)
    if meta is None:
        raise Http404
    patient = client = weight = None
    if patient_pk is not None:
        patient = get_object_or_404(Patient.objects.select_related('client'), pk=patient_pk)
        client = patient.client
        weight = patient.weights.order_by('-date', '-pk').first()
    org = request.organization
    user = request.user
    doctor = user if getattr(user, 'role', '') in ('doctor', 'admin') else getattr(org, 'default_doctor', None)
    return render(request, f'clients/consents/{key}.html', {
        'meta': meta, 'org': org, 'patient': patient, 'client': client, 'weight': weight,
        'doctor_name': (doctor.get_full_name() or doctor.username) if doctor else '',
        'today': timezone.localdate(), 'L': BLANK,
    })
