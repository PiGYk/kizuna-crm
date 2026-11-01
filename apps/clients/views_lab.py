"""Бланки лабораторних аналізів: заповнити, змінити, надрукувати, видалити (ANVAR 01.11.2026)."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from .forms import LabResultForm
from .lab_panels import DESCRIPTIVE, PANELS, learn_norms, merge_rows, rows_from_post, template_rows
from .models import LabResult, Patient


def _lab_or_404(request, pk):
    return get_object_or_404(LabResult, pk=pk, patient__client__organization=request.organization)


_MATERIAL_HINT = {
    'biochemistry': 'напр. сироватка крові', 'hematology': 'напр. кров з ЕДТА',
    'cytology': 'напр. мазок-відбиток, пунктат', 'histology': 'напр. біоптат шкіри', 'other': 'напр. сеча',
}


def _render_form(request, lab, form, rows):
    org = request.organization
    species = lab.patient.species
    form.fields['material'].widget.attrs['placeholder'] = _MATERIAL_HINT.get(lab.panel, '')
    if lab.panel == 'other':
        form.fields['title'].widget.attrs['placeholder'] = 'напр. Загальний аналіз сечі'
    return render(request, 'clients/lab_form.html', {
        'lab': lab, 'patient': lab.patient, 'form': form, 'rows': rows,
        'descriptive': lab.panel in DESCRIPTIVE,
        'has_norms': species in ('dog', 'cat') or bool((org.lab_norms or {}).get(species)),
        'doctors': get_user_model().practitioners(org, keep=lab.doctor_id).order_by('last_name', 'first_name'),
        'doctor_value': request.POST.get('doctor', str(lab.doctor_id or '')),
    })


def _save(request, lab, form):
    lab = form.save(commit=False)
    lab.rows = rows_from_post(request.POST)
    doctor_id = request.POST.get('doctor') or None
    lab.doctor = (get_object_or_404(get_user_model(), pk=doctor_id, organization=request.organization)
                  if doctor_id else None)
    if not lab.pk:
        lab.created_by = request.user
    lab.save()
    org = request.organization
    learned = learn_norms(lab.rows, lab.patient.species, org.lab_norms)
    if learned is not None:
        org.lab_norms = learned
        org.save(update_fields=['lab_norms'])
    return lab


@login_required
def lab_create(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk, client__organization=request.organization)
    panel = request.POST.get('panel') or request.GET.get('panel') or 'biochemistry'
    if panel not in PANELS:
        raise Http404
    org = request.organization
    me = request.user if request.user.takes_visits and request.user.role in ('admin', 'doctor') else None
    lab = LabResult(patient=patient, panel=panel, doctor=org.default_doctor or me)
    if request.method == 'POST':
        form = LabResultForm(request.POST, instance=lab)
        if form.is_valid():
            lab = _save(request, lab, form)
            messages.success(request, f'«{lab.display_title}» збережено')
            return redirect('clients:lab_edit', pk=lab.pk)
        rows = rows_from_post(request.POST, keep_empty=True)
    else:
        form = LabResultForm(instance=lab)
        rows = template_rows(panel, patient.species, org.lab_norms)
    return _render_form(request, lab, form, rows)


@login_required
def lab_edit(request, pk):
    lab = _lab_or_404(request, pk)
    if request.method == 'POST':
        form = LabResultForm(request.POST, instance=lab)
        if form.is_valid():
            lab = _save(request, lab, form)
            messages.success(request, 'Збережено')
            return redirect('clients:lab_edit', pk=lab.pk)
        rows = rows_from_post(request.POST, keep_empty=True)
    else:
        form = LabResultForm(instance=lab)
        rows = merge_rows(lab.panel, lab.patient.species, lab.rows, request.organization.lab_norms)
    return _render_form(request, lab, form, rows)


@login_required
def lab_pdf(request, pk):
    lab = _lab_or_404(request, pk)
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse('WeasyPrint не встановлено', status=500)
    from pathlib import Path
    from django.conf import settings
    html = render_to_string('clients/lab_pdf.html', {
        'lab': lab, 'patient': lab.patient, 'clinic': request.organization, 'rows': lab.rows_with_flags(),
        'descriptive': lab.panel in DESCRIPTIVE,
        'font_dir': (Path(settings.BASE_DIR) / 'static' / 'fonts' / 'fixel').as_uri(),
    })
    pdf = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'filename="analiz-{lab.pk}-{lab.date:%d%m%Y}.pdf"'
    return response


@login_required
@require_POST
def lab_delete(request, pk):
    lab = _lab_or_404(request, pk)
    patient_pk, title = lab.patient_id, lab.display_title
    lab.delete()
    messages.success(request, f'«{title}» видалено')
    return redirect('clients:patient_detail', pk=patient_pk)
