from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy, reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required

from apps.billing.models import Invoice
from .forms import ClientForm, PatientForm, VisitForm, VaccineForm, AnalysisForm, WeightForm, HospitalizationForm
from .models import Client, Patient, Visit, Vaccine, PatientAnalysis, WeightRecord, Hospitalization


class PatientListView(LoginRequiredMixin, ListView):
    model = Patient
    template_name = 'clients/patient_list.html'
    context_object_name = 'patients'
    paginate_by = 40

    def get_queryset(self):
        qs = Patient.objects.select_related('client', 'assigned_doctor')
        if self.request.organization:
            qs = qs.filter(client__organization=self.request.organization)
        # Soft-delete: за замовч ховаємо архівованих; ?archived=1 показує лише архів.
        # Без цього «Видалити» архівувало тварину, а вона лишалась у списку —
        # персонал читав це як «видалення не працює» (скарга 26.07).
        archived_view = self.request.GET.get('archived') == '1'
        qs = qs.filter(is_archived=archived_view)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(client__first_name__icontains=q) |
                Q(client__last_name__icontains=q) |
                Q(breed__icontains=q) |
                Q(microchip__icontains=q)          # знайти тварину за номером чіпа
            )
        species = self.request.GET.get('species', '')
        if species:
            qs = qs.filter(species=species)
        sort = self.request.GET.get('sort', '')
        if sort == 'new':
            qs = qs.order_by('-created_at')
        elif sort == 'old':
            qs = qs.order_by('created_at')
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        ctx['sort'] = self.request.GET.get('sort', '')
        ctx['species'] = self.request.GET.get('species', '')
        ctx['archived'] = self.request.GET.get('archived') == '1'
        return ctx


class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = 'clients/list.html'
    context_object_name = 'clients'
    paginate_by = 30

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('patients')
        if self.request.organization:
            qs = qs.filter(organization=self.request.organization)
        # Soft-delete: за замовч ховаємо архівованих; ?archived=1 показує лише архів
        archived_view = self.request.GET.get('archived') == '1'
        qs = qs.filter(is_archived=archived_view)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(phone__icontains=q)
            )
        activity = self.request.GET.get('activity', '')
        if activity == 'inactive':
            six_months_ago = timezone.now().date() - timedelta(days=180)
            qs = qs.filter(
                ~Q(patients__visits__date__date__gte=six_months_ago)
            ).distinct()
        elif activity == 'active':
            six_months_ago = timezone.now().date() - timedelta(days=180)
            qs = qs.filter(
                patients__visits__date__date__gte=six_months_ago
            ).distinct()
        sort = self.request.GET.get('sort', '')
        if sort == 'name':
            qs = qs.order_by('last_name', 'first_name')
        elif sort == 'name_desc':
            qs = qs.order_by('-last_name', '-first_name')
        elif sort == 'new':
            qs = qs.order_by('-created_at')
        elif sort == 'old':
            qs = qs.order_by('created_at')
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        ctx['sort'] = self.request.GET.get('sort', '')
        ctx['activity'] = self.request.GET.get('activity', '')
        ctx['archived'] = self.request.GET.get('archived') == '1'
        return ctx


class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = 'clients/form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['org'] = self.request.organization
        return kwargs

    def get_success_url(self):
        return reverse('clients:detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        form.instance.organization = self.request.organization
        messages.success(self.request, 'Клієнта додано')
        return super().form_valid(form)


class ClientUpdateView(LoginRequiredMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = 'clients/form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['org'] = self.request.organization
        return kwargs

    def get_success_url(self):
        return reverse('clients:detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Збережено')
        return super().form_valid(form)


class ClientDetailView(LoginRequiredMixin, DetailView):
    model = Client
    template_name = 'clients/detail.html'
    context_object_name = 'client'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['patients'] = self.object.patients.select_related('assigned_doctor').all()
        return ctx


@login_required
def patient_create(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    org = request.organization
    form = PatientForm(request.POST or None, request.FILES or None, org=org)
    if request.method == 'POST' and form.is_valid():
        patient = form.save(commit=False)
        patient.client = client
        patient.save()
        messages.success(request, f'Пацієнта {patient.name} додано')
        return redirect('clients:patient_detail', pk=patient.pk)
    return render(request, 'clients/patient_form.html', {'form': form, 'client': client})


@login_required
def patient_update(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    org = request.organization
    form = PatientForm(request.POST or None, request.FILES or None, instance=patient, org=org)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Збережено')
        return redirect('clients:patient_detail', pk=patient.pk)
    return render(request, 'clients/patient_form.html', {'form': form, 'client': patient.client, 'patient': patient})


class PatientDetailView(LoginRequiredMixin, DetailView):
    model = Patient
    template_name = 'clients/patient_detail.html'
    context_object_name = 'patient'

    def get_context_data(self, **kwargs):
        from django.contrib.auth import get_user_model
        from datetime import date
        ctx = super().get_context_data(**kwargs)
        # N+1 fix: prefetch усі relation що використовує template
        ctx['visits'] = (
            self.object.visits
            .select_related('doctor')
            .prefetch_related('prescriptions')
            .all()
        )
        ctx['vaccines'] = self.object.vaccines.select_related('doctor').all()
        ctx['invoices'] = (
            self.object.invoices
            .select_related('doctor')
            .prefetch_related('lines__service', 'lines__product')
            .filter(status='paid')
            .all()
        )
        ctx['analyses'] = list(self.object.analyses.all())
        ctx['lab_results'] = list(self.object.lab_results.select_related('doctor'))
        ctx['analyses_total'] = len(ctx['analyses']) + len(ctx['lab_results'])
        from .models import LabResult
        ctx['lab_panels'] = LabResult.Panel.choices
        # Підсумок рахунків — на телефоні перелік згорнутий у рядок «N · сума ₴»
        ctx['invoices'] = list(ctx['invoices'])
        ctx['invoices_total'] = sum((inv.total or 0) for inv in ctx['invoices'])
        # Optional related: можуть не існувати на старих моделях
        for attr in ('ultrasounds', 'health_checks', 'documents', 'hospitalizations'):
            if hasattr(self.object, attr):
                qs = getattr(self.object, attr).all()
                # Спробувати select_related для doctor якщо є
                if hasattr(qs.model, 'doctor'):
                    qs = qs.select_related('doctor')
                ctx[attr] = qs
        org = self.request.organization
        default_doc = org.get_default_doctor(self.request.user) if org else self.request.user
        ctx['visit_form'] = VisitForm(initial={'doctor': default_doc}, org=org)
        ctx['vaccine_form'] = VaccineForm(initial={'doctor': default_doc}, org=org)
        ctx['analysis_form'] = AnalysisForm(initial={'date': date.today()})
        ctx['weight_form'] = WeightForm(initial={'date': date.today()})
        ctx['weights'] = list(self.object.weights.order_by('date').all())
        from .alerts import patient_alerts
        ctx['alerts'] = patient_alerts(self.object, list(ctx['vaccines']), ctx['weights'], ctx['invoices'], date.today())
        ctx['doctors'] = get_user_model().practitioners(
            self.request.organization, keep=self.object.assigned_doctor_id,
        ).order_by('last_name', 'first_name')
        return ctx


def _appointment_from_request(request, patient):
    """Запис календаря, з якого проводять прийом (?appointment=N або hidden-поле).

    Беремо тільки запис своєї клініки і саме цієї тварини — щоб параметром в
    адресі не можна було підчепити чужий запис.
    """
    from apps.appointments.models import Appointment
    raw = request.POST.get('appointment') or request.GET.get('appointment')
    if not raw:
        return None
    try:
        appt_id = int(raw)
    except (TypeError, ValueError):
        return None
    return Appointment.objects.filter(
        pk=appt_id, patient_id=patient.pk, organization=request.organization
    ).first()


@login_required
def visit_create(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    org = request.organization
    default_doc = org.get_default_doctor(request.user) if org else request.user
    appt = _appointment_from_request(request, patient)

    # Дата обовʼязкова, а підставлялась порожньою — кожен прийом починався з
    # ручного набору дати й часу. Тепер за замовчуванням «зараз».
    initial = {
        'doctor': default_doc,
        'date': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
    }
    if appt:
        # Лікаря і час беремо із запису — щоб лікарю лишилось тільки написати текст.
        if appt.doctor_id:
            initial['doctor'] = appt.doctor
        initial['date'] = timezone.localtime(appt.starts_at).strftime('%Y-%m-%dT%H:%M')

    form = VisitForm(request.POST or None, initial=initial, org=org)
    if request.method == 'POST' and form.is_valid():
        visit = form.save(commit=False)
        visit.patient = patient
        if appt:
            visit.appointment = appt
        visit.save()
        if appt and appt.status != appt.Status.COMPLETED:
            # Автозакриття: 98% минулих записів висіли «заплановано», бо статус
            # ніхто не веде руками. Провів прийом — запис закрито.
            appt.status = appt.Status.COMPLETED
            appt.save(update_fields=['status'])
            messages.success(request, 'Прийом збережено, запис у календарі закрито.')
        else:
            messages.success(request, 'Візит додано')
        return redirect('clients:patient_detail', pk=patient.pk)
    return render(request, 'clients/visit_form.html', {
        'form': form, 'patient': patient,
        'side_analyses': _recent_analyses(patient),
        'appointment': appt,
    })


def _recent_analyses(patient, limit=8):
    """Останні аналізи тварини — щоб лікар бачив їх ПОРУЧ під час прийому.

    Прохання Ірпеня 10.08: «аналізи є внизу списком, а коли дивишся прийом і
    призначення — краще, щоб це було в одному місці».
    """
    return list(
        PatientAnalysis.objects
        .filter(patient=patient)
        .order_by('-date', '-id')[:limit]
    )


@login_required
@require_POST
def visit_delete(request, pk):
    """Видалити прийом (ANVAR 02.11: «открыл приём два раза и не могу удалить»). Порожній — будь-хто, хто
    бачить картку; із записами чи призначеннями — лише адміністратор. Призначення видаляються разом із прийомом,
    документи, УЗД і записи щоденника лишаються в картці (на прийом вони посилаються з SET_NULL).
    Видалення пише журнал аудиту (сигнал post_delete)."""
    from django.utils import timezone
    visit = get_object_or_404(Visit, pk=pk, patient__client__organization=request.organization)
    patient_pk = visit.patient_id
    if not visit.is_blank and not (request.user.is_superuser or request.user.is_admin()):
        messages.error(request, 'Прийом із записами може видалити лише адміністратор.')
        return redirect('clients:patient_detail', pk=patient_pk)
    when = timezone.localtime(visit.date).strftime('%d.%m.%Y %H:%M')
    visit.delete()
    messages.success(request, f'Прийом {when} видалено.')
    return redirect('clients:patient_detail', pk=patient_pk)


@login_required
@require_POST
def visit_duplicate(request, pk):
    from django.utils import timezone
    original = get_object_or_404(
        Visit, pk=pk, patient__client__organization=request.organization
    )
    org = request.organization
    default_doc = org.get_default_doctor(request.user) if org else request.user
    copy = Visit.objects.create(
        patient=original.patient,
        doctor=default_doc,
        date=timezone.now(),
        complaint=original.complaint,
        exam=original.exam,
        diagnosis=original.diagnosis,
        treatment=original.treatment,
        notes=original.notes,
    )
    return redirect('clients:visit_edit', pk=copy.pk)


@login_required
def visit_update(request, pk):
    visit = get_object_or_404(
        Visit, pk=pk, patient__client__organization=request.organization
    )
    org = request.organization
    form = VisitForm(request.POST or None, instance=visit, org=org)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Збережено')
        return redirect('clients:patient_detail', pk=visit.patient.pk)
    return render(request, 'clients/visit_form.html', {
        'form': form, 'patient': visit.patient, 'visit': visit,
        'side_analyses': _recent_analyses(visit.patient),
        'appointment': visit.appointment,
    })


@login_required
def visit_pdf(request, pk):
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    visit = get_object_or_404(
        Visit, pk=pk, patient__client__organization=request.organization
    )
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse('WeasyPrint не встановлено', status=500)
    base_url = request.build_absolute_uri('/')
    ctx = {'visit': visit, 'patient': visit.patient, 'clinic': request.organization, 'request': request}
    if request.GET.get('copies') == '2':
        # Два примірники одним файлом (питання ANVAR 31.10): власнику і клініці,
        # де власник розписується, що отримав рекомендації.
        docs = [HTML(string=render_to_string('clients/visit_pdf.html', {**ctx, 'copy_label': label}),
                     base_url=base_url).render()
                for label in ('Примірник власника', 'Примірник клініки')]
        pdf = docs[0].copy([page for d in docs for page in d.pages]).write_pdf()
    else:
        pdf = HTML(string=render_to_string('clients/visit_pdf.html', ctx), base_url=base_url).write_pdf()
    filename = f"visit-{visit.patient.name}-{visit.date:%d%m%Y}.pdf"
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'filename="{filename}"'
    return response


@login_required
def vaccine_create(request, patient_pk):
    from apps.inventory.models import Product
    patient = get_object_or_404(Patient, pk=patient_pk)
    org = request.organization
    default_doc = org.get_default_doctor(request.user) if org else request.user
    form = VaccineForm(request.POST or None, initial={'doctor': default_doc}, org=org)
    if request.method == 'POST' and form.is_valid():
        vaccine = form.save(commit=False)
        vaccine.patient = patient
        vaccine.save()
        messages.success(request, 'Вакцинацію додано')
        return redirect('clients:patient_detail', pk=patient.pk)
    products = Product.objects.filter(
        organization=request.organization
    ).order_by('name').values_list('name', flat=True)
    return render(request, 'clients/vaccine_form.html', {
        'form': form, 'patient': patient, 'product_names': list(products),
    })


@login_required
def vaccine_update(request, pk):
    from apps.inventory.models import Product
    vaccine = get_object_or_404(Vaccine, pk=pk)
    org = request.organization
    form = VaccineForm(request.POST or None, instance=vaccine, org=org)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Збережено')
        return redirect('clients:patient_detail', pk=vaccine.patient.pk)
    products = Product.objects.filter(
        organization=vaccine.patient.client.organization
    ).order_by('name').values_list('name', flat=True)
    return render(request, 'clients/vaccine_form.html', {
        'form': form, 'patient': vaccine.patient, 'vaccine': vaccine,
        'product_names': list(products),
    })


@login_required
def patient_set_doctor(request, pk):
    from django.contrib.auth import get_user_model
    from django.http import HttpResponse
    patient = get_object_or_404(Patient, pk=pk, client__organization=request.organization)
    if request.method == 'POST':
        doctor_id = request.POST.get('assigned_doctor') or None
        if doctor_id:
            User = get_user_model()
            patient.assigned_doctor = get_object_or_404(
                User, pk=doctor_id, organization=request.organization
            )
        else:
            patient.assigned_doctor = None
        patient.save(update_fields=['assigned_doctor'])
    doctors = get_user_model().practitioners(
        request.organization, keep=patient.assigned_doctor_id,
    ).order_by('last_name', 'first_name')
    return render(request, 'clients/partials/patient_doctor.html', {
        'patient': patient,
        'doctors': doctors,
    })


@login_required
def analysis_create(request, patient_pk):
    patient = get_object_or_404(
        Patient, pk=patient_pk, client__organization=request.organization
    )
    if request.method == 'POST':
        form = AnalysisForm(request.POST, request.FILES)
        if form.is_valid():
            analysis = form.save(commit=False)
            analysis.patient = patient
            analysis.uploaded_by = request.user
            analysis.save()
            messages.success(request, 'Аналіз додано')
        else:
            messages.error(request, 'Помилка при завантаженні')
    return redirect('clients:patient_detail', pk=patient_pk)


@login_required
def analysis_delete(request, pk):
    analysis = get_object_or_404(
        PatientAnalysis, pk=pk, patient__client__organization=request.organization
    )
    patient_pk = analysis.patient.pk
    if request.method == 'POST':
        analysis.image.delete(save=False)
        analysis.delete()
        messages.success(request, 'Видалено')
    return redirect('clients:patient_detail', pk=patient_pk)


# HTMX live search — повертає partial з результатами
@login_required
def client_search(request):
    q = request.GET.get('q', '').strip()
    clients = []
    if len(q) >= 2:
        clients = Client.objects.filter(
            organization=request.organization,
        ).filter(
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(phone__icontains=q) |
            Q(patients__microchip__icontains=q)    # знайшли чіп -> бачимо власника
        ).distinct().prefetch_related('patients')[:10]
    mode = request.GET.get('mode', '')
    return render(request, 'clients/partials/search_results.html', {'clients': clients, 'q': q, 'mode': mode})


@login_required
@require_POST
def microchip_save(request, patient_pk):
    """Запис/зміна мікрочіпа прямо з картки пацієнта (плашка між вакцинами і вагою)."""
    patient = get_object_or_404(
        Patient, pk=patient_pk, client__organization=request.organization
    )
    # Валідація на межі: з чіпа читаються цифри (15) або старий літерно-цифровий код.
    raw = (request.POST.get('microchip') or '').strip().replace(' ', '').replace('-', '')
    chip = ''.join(ch for ch in raw if ch.isalnum())[:30]
    if raw and not chip:
        messages.error(request, 'Номер чіпа може містити тільки цифри й літери')
        return redirect('clients:patient_detail', pk=patient_pk)

    date_raw = (request.POST.get('microchip_date') or '').strip()
    chip_date = None
    if date_raw:
        from datetime import datetime as _dt
        try:
            chip_date = _dt.strptime(date_raw, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Дата чіпування у незрозумілому форматі')
            return redirect('clients:patient_detail', pk=patient_pk)

    # Той самий номер в іншої тварини цієї клініки — майже завжди помилка набору.
    if chip:
        twin = Patient.objects.filter(
            client__organization=request.organization, microchip=chip,
        ).exclude(pk=patient.pk).first()
        if twin:
            messages.error(
                request,
                'Номер %s вже стоїть у тварини «%s» (власник %s). Перевірте номер.'
                % (chip, twin.name, twin.client),
            )
            return redirect('clients:patient_detail', pk=patient_pk)

    patient.microchip = chip
    patient.microchip_date = chip_date
    patient.save(update_fields=['microchip', 'microchip_date'])
    messages.success(
        request,
        'Мікрочіп %s записано' % chip if chip else 'Мікрочіп прибрано з картки',
    )
    return redirect('clients:patient_detail', pk=patient_pk)


@login_required
def weight_add(request, patient_pk):
    patient = get_object_or_404(
        Patient, pk=patient_pk, client__organization=request.organization
    )
    if request.method == 'POST':
        form = WeightForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.patient = patient
            record.recorded_by = request.user
            record.save()
            messages.success(request, f'Вагу {record.weight} кг записано')
    return redirect('clients:patient_detail', pk=patient_pk)


@login_required
def weight_delete(request, pk):
    record = get_object_or_404(
        WeightRecord, pk=pk, patient__client__organization=request.organization
    )
    patient_pk = record.patient.pk
    if request.method == 'POST':
        record.delete()
    return redirect('clients:patient_detail', pk=patient_pk)


@login_required
def patients_by_period(request):
    from datetime import date, timedelta
    from django.db.models import Max

    # Дефолт: останні 30 днів
    today = date.today()
    default_from = today - timedelta(days=30)

    date_from_str = request.GET.get('date_from', default_from.isoformat())
    date_to_str = request.GET.get('date_to', today.isoformat())

    try:
        date_from = date.fromisoformat(date_from_str)
    except ValueError:
        date_from = default_from
    try:
        date_to = date.fromisoformat(date_to_str)
    except ValueError:
        date_to = today

    # Пацієнти у яких є протоколи (візити) за вказаний період
    patients_qs = (
        Patient.objects
        .filter(visits__date__date__range=(date_from, date_to))
        .select_related('client', 'assigned_doctor')
        .annotate(last_visit=Max('visits__date'))
        .distinct()
        .order_by('-last_visit')
    )

    return render(request, 'clients/patients_period.html', {
        'patients': patients_qs,
        'date_from': date_from,
        'date_to': date_to,
        'count': patients_qs.count(),
    })


def _admin_only(request, back):
    if request.user.is_admin():
        return None
    messages.error(request, 'Видаляти назавжди може лише адміністратор.')
    return redirect(back)


@login_required
def client_delete(request, pk):
    """Видалити клієнта НАЗАВЖДИ разом із тваринами, медичною історією, файлами й
    записами в розкладі (наказ Олега 31.10.2026: «видалив — значить видалив»).
    Рахунки — лише за явним вибором, так само як у розділі «Рахунки»."""
    from . import purge
    client = get_object_or_404(Client, pk=pk)
    denied = _admin_only(request, reverse('clients:detail', args=[pk]))
    if denied:
        return denied
    summary = purge.client_summary(client)
    if request.method == 'POST':
        with_invoices = request.POST.get('with_invoices') == '1'
        restore = request.POST.get('restore')
        if summary['invoices'] and not with_invoices:
            messages.error(request, 'У клієнта є рахунки — позначте, що видаляєте разом із ними.')
            return redirect('clients:delete', pk=pk)
        if summary['invoices'] and summary['paid_written_off'] and restore not in ('yes', 'no'):
            messages.error(request, 'Оберіть, чи повертати товари з оплачених рахунків на склад.')
            return redirect('clients:delete', pk=pk)
        name = f'{client.first_name} {client.last_name}'.strip()
        n_patients, n_invoices = purge.delete_client(
            client, request.user, with_invoices=with_invoices, restore_stock=(restore == 'yes'))
        tail = f', рахунків: {n_invoices}' if n_invoices else ''
        messages.success(request, f'Клієнта {name} видалено назавжди (тварин: {n_patients}{tail}).')
        return redirect('clients:list')
    return render(request, 'clients/confirm_delete.html', {'client': client, 's': summary})


@login_required
def patient_delete(request, pk):
    """Видалити тварину НАЗАВЖДИ з медичною історією і файлами. Рахунки лишаються за клієнтом."""
    from . import purge
    patient = get_object_or_404(Patient, pk=pk)
    client_pk = patient.client_id
    denied = _admin_only(request, reverse('clients:patient_detail', args=[pk]))
    if denied:
        return denied
    if request.method == 'POST':
        name = patient.name
        purge.delete_patient(patient)
        messages.success(request, f'Пацієнта {name} видалено назавжди.')
        return redirect('clients:detail', pk=client_pk)
    return render(request, 'clients/patient_confirm_delete.html',
                  {'patient': patient, 's': purge.patient_summary(patient)})


@login_required
def archive_purge(request):
    """Вичистити архів — те, що до 31.10.2026 «видаляли» в архів."""
    from . import purge
    denied = _admin_only(request, reverse('clients:patient_list') + '?archived=1')
    if denied:
        return denied
    org = request.organization
    if request.method == 'POST':
        r = purge.purge_archive(org)
        msg = f'Архів очищено: клієнтів {r["clients"]}, тварин {r["patients"]}.'
        if r['kept']:
            msg += (' Лишились клієнти з рахунками (видаляйте по одному, щоб вирішити, що робити з рахунками): '
                    + ', '.join(f'{c.first_name} {c.last_name}'.strip() for c in r['kept']))
        messages.success(request, msg)
        return redirect(reverse('clients:list') + '?archived=1')
    return render(request, 'clients/archive_purge.html', {'c': purge.archive_counts(org)})


def _dt_local(value):
    """Значення для <input type="datetime-local"> у часовому поясі клініки."""
    from django.utils import timezone
    return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M') if value else ''


_HOSP_PERIODS = (30, 90, 365)


def _hospital_stats(days):
    """Підсумки виписок за період по лікарях (ANVAR 01.11: «якщо в одного лікаря всі вмирають —
    будуть питання»). Рахуємо за датою виписки; без результату — окремою колонкою."""
    from datetime import timedelta
    from django.db.models import Count, Q
    from django.utils import timezone
    O = Hospitalization.Outcome
    groups = {
        'good': [O.RECOVERED, O.IMPROVED], 'same': [O.NO_CHANGE, O.TRANSFERRED],
        'refused': [O.REFUSED], 'euthanasia': [O.EUTHANASIA], 'died': [O.DIED], 'none': [''],
    }
    rows = (Hospitalization.objects
            .filter(status='discharged', discharged_at__gte=timezone.now() - timedelta(days=days))
            .values('doctor_id', 'doctor__first_name', 'doctor__last_name', 'doctor__username')
            .annotate(total=Count('id'), **{k: Count('id', filter=Q(outcome__in=v)) for k, v in groups.items()})
            .order_by('-total'))
    rows = list(rows)
    for r in rows:
        name = f"{r['doctor__first_name'] or ''} {r['doctor__last_name'] or ''}".strip()
        r['name'] = name or r['doctor__username'] or 'Лікаря не вказано'
    totals = {k: sum(r[k] for r in rows) for k in ['total', *groups]}
    return rows, totals


@login_required
def hospitalization_list(request):
    active = Hospitalization.objects.filter(status='active').select_related(
        'patient__client', 'doctor'
    )
    recent = Hospitalization.objects.filter(status='discharged').select_related(
        'patient__client', 'doctor'
    ).order_by('-discharged_at')[:20]
    ctx = {'active': active, 'recent': recent}
    if request.user.is_admin():
        try:
            days = int(request.GET.get('days', 90))
        except ValueError:
            days = 90
        days = days if days in _HOSP_PERIODS else 90
        ctx['stats'], ctx['stats_total'] = _hospital_stats(days)
        ctx['stats_days'], ctx['stats_periods'] = days, _HOSP_PERIODS
    return render(request, 'clients/hospitalization_list.html', ctx)


@login_required
def hospitalization_create(request, patient_pk):
    from django.contrib.auth import get_user_model
    patient = get_object_or_404(
        Patient, pk=patient_pk, client__organization=request.organization
    )
    doctors = get_user_model().practitioners(request.organization).order_by('last_name', 'first_name')
    if request.method == 'POST':
        form = HospitalizationForm(request.POST)
        if form.is_valid():
            hosp = form.save(commit=False)
            hosp.patient = patient
            hosp.organization = request.organization
            doctor_id = request.POST.get('doctor') or None
            if doctor_id:
                hosp.doctor = get_object_or_404(
                    get_user_model(),
                    pk=doctor_id,
                    organization=request.organization,
                )
            hosp.save()
            messages.success(request, f'{patient.name} госпіталізовано')
            return redirect('clients:hospitalization_list')
    else:
        form = HospitalizationForm()
    from django.utils import timezone
    return render(request, 'clients/hospitalization_form.html', {
        'patient': patient, 'doctors': doctors, 'form': form,
        'admitted_value': request.POST.get('admitted_at') or _dt_local(timezone.now()),
        'now_value': _dt_local(timezone.now()),
        'doctor_value': request.POST.get('doctor', ''),
    })


@login_required
def hospitalization_discharge(request, pk):
    """Виписка — або результат давнішої виписки (тоді статус уже «виписаний», правимо поля)."""
    from django.utils import timezone
    from .forms import DischargeForm
    hosp = get_object_or_404(
        Hospitalization, pk=pk, patient__client__organization=request.organization
    )
    if request.method == 'POST':
        form = DischargeForm(request.POST, instance=hosp)
        if form.is_valid():
            hosp = form.save(commit=False)
            was_active = hosp.status != 'discharged'
            hosp.status = 'discharged'
            hosp.save(update_fields=['status', 'discharged_at', 'outcome', 'discharge_condition', 'discharge_notes'])
            messages.success(request, f'{hosp.patient.name} виписано' if was_active else 'Результат виписки збережено')
            return redirect('clients:hospitalization_list')
        discharged_value = request.POST.get('discharged_at', '')
    else:
        form = DischargeForm(instance=hosp)
        discharged_value = _dt_local(hosp.discharged_at or timezone.now())
    return render(request, 'clients/hospitalization_discharge.html', {
        'hosp': hosp, 'form': form, 'discharged_value': discharged_value,
        'now_value': _dt_local(timezone.now()), 'admitted_value': _dt_local(hosp.admitted_at),
    })


@login_required
def vaccines_overdue(request):
    from datetime import date, timedelta

    today = date.today()
    week_ahead = today + timedelta(days=7)
    month_ahead = today + timedelta(days=30)

    overdue = (
        Vaccine.objects
        .filter(next_date__lt=today, patient__client__organization=request.organization)
        .select_related('patient__client', 'patient__assigned_doctor')
        .order_by('next_date')
    )

    due_week = (
        Vaccine.objects
        .filter(next_date__gte=today, next_date__lte=week_ahead, patient__client__organization=request.organization)
        .select_related('patient__client', 'patient__assigned_doctor')
        .order_by('next_date')
    )

    due_month = (
        Vaccine.objects
        .filter(next_date__gt=week_ahead, next_date__lte=month_ahead, patient__client__organization=request.organization)
        .select_related('patient__client', 'patient__assigned_doctor')
        .order_by('next_date')
    )

    all_vaccines = (
        Vaccine.objects
        .filter(patient__client__organization=request.organization)
        .select_related('patient__client', 'patient__assigned_doctor', 'doctor')
        .order_by('-date')
    )

    return render(request, 'clients/vaccines_overdue.html', {
        'overdue': overdue,
        'due_week': due_week,
        'due_month': due_month,
        'all_vaccines': all_vaccines,
        'today': today,
    })


# ── Зведена медкартка PDF ──────────────────────────────────────────────
@login_required
def patient_medical_card(request, pk):
    """Повна медична картка пацієнта у PDF."""
    patient = get_object_or_404(
        Patient, pk=pk, client__organization=request.organization
    )
    visits = patient.visits.select_related('doctor').order_by('-date')
    vaccines = patient.vaccines.order_by('-date')
    weights = patient.weights.order_by('date')
    invoices = Invoice.objects.filter(patient=patient).select_related('doctor').order_by('-created_at')

    from django.template.loader import render_to_string
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse('WeasyPrint не встановлено', status=500)

    html_string = render_to_string('clients/medical_card_pdf.html', {
        'patient': patient,
        'client': patient.client,
        'visits': visits,
        'vaccines': vaccines,
        'weights': weights,
        'invoices': invoices,
        'clinic': request.organization,
        'request': request,
    })
    pdf = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'filename="medical-card-{patient.name}.pdf"'
    return response


# ── Швидкий візит ───────────────────────────────────────────────────────
@login_required
def quick_visit(request, patient_pk):
    """Швидкий візит — мінімальна форма для простого огляду."""
    patient = get_object_or_404(
        Patient, pk=patient_pk, client__organization=request.organization
    )
    if request.method == 'POST':
        from django.utils import timezone
        org = request.organization
        default_doc = org.get_default_doctor(request.user) if org else request.user
        Visit.objects.create(
            patient=patient,
            doctor=default_doc,
            date=timezone.now(),
            complaint=request.POST.get('complaint', '').strip() or 'Плановий огляд',
            exam=request.POST.get('exam', '').strip(),
            diagnosis=request.POST.get('diagnosis', '').strip(),
            treatment=request.POST.get('treatment', '').strip(),
            notes=request.POST.get('notes', '').strip(),
        )
        messages.success(request, 'Візит записано.')
        return redirect('clients:patient_detail', pk=patient_pk)
    return render(request, 'clients/partials/quick_visit_modal.html', {'patient': patient})


# ── Фото upload (HTMX) ─────────────────────────────────────────────────
@login_required
@require_POST
def patient_photo_upload(request, pk):
    """HTMX: оновлення фото пацієнта прямо з картки."""
    patient = get_object_or_404(
        Patient, pk=pk, client__organization=request.organization
    )
    photo = request.FILES.get('photo')
    if photo:
        # Видалити старе фото
        if patient.photo:
            patient.photo.delete(save=False)
        patient.photo = photo
        patient.save()
        messages.success(request, 'Фото оновлено.')
    return redirect('clients:patient_detail', pk=pk)


# ── Diagnosis suggestions JSON ──────────────────────────────────────────
@login_required
def diagnosis_suggestions(request):
    """Підказки діагнозів — з того, що вже писали в цій клініці.

    Прохання Ірпеня 10.08: «Діагноз — чи можна зробити випадаючий список?».
    Окремий довідник ніхто б не заповнював, тому список збирається сам з
    історії візитів: що частіше писали, те вище. Поле Quill зберігає HTML,
    тому теги знімаємо; беремо лише короткі записи — довгий опис це вже не
    діагноз, а текст прийому.
    """
    import re
    from collections import Counter

    q = request.GET.get('q', '').strip().lower()
    # Клініка зі своїми назвами розділів може писати діагноз в інше поле (ANVAR — у treatment).
    field = getattr(request.organization, 'visit_suggest_diagnosis', 'diagnosis')
    raw = (
        Visit.objects
        .filter(patient__client__organization=request.organization)
        .exclude(**{field: ''})
        .order_by('-date')
        .values_list(field, flat=True)[:2000]
    )

    counter = Counter()
    for html in raw:
        text = re.sub(r'<[^>]+>', ' ', html or '')
        text = re.sub(r'&nbsp;?', ' ', text)
        for part in re.split(r'[\n;]+', text):
            name = ' '.join(part.split()).strip(' .,•-')
            if 3 <= len(name) <= 120:
                counter[name] += 1

    items = [n for n, _ in counter.most_common(400)]
    if q:
        items = [n for n in items if q in n.lower()]
    return JsonResponse({'results': items[:25]})


# ── Breed suggestions JSON ──────────────────────────────────────────────
@login_required
def breed_suggestions(request):
    """JSON з популярними породами для datalist."""
    species = request.GET.get('species', '')
    breeds = (
        Patient.objects
        .filter(client__organization=request.organization)
        .exclude(breed='')
        .values_list('breed', flat=True)
        .distinct()
        .order_by('breed')
    )
    if species:
        breeds = breeds.filter(species=species)
    return JsonResponse({'breeds': list(breeds[:50])})


# ── Вага — alert перевірка ──────────────────────────────────────────────
@login_required
def weight_alert_check(request, patient_pk):
    """Перевіряє різку зміну ваги пацієнта."""
    patient = get_object_or_404(Patient, pk=patient_pk)
    weights = list(patient.weights.order_by('-date')[:2])
    alert = None
    if len(weights) >= 2:
        current = weights[0].weight
        previous = weights[1].weight
        if previous > 0:
            change_pct = abs(float(current - previous) / float(previous) * 100)
            if change_pct > 15:
                direction = 'набрав' if current > previous else 'втратив'
                alert = {
                    'message': f'{patient.name} {direction} {change_pct:.1f}% ваги ({previous}→{current} кг)',
                    'severity': 'warning' if change_pct < 25 else 'danger',
                }
    return JsonResponse({'alert': alert})


# ── Рецепти CRUD ────────────────────────────────────────────────────────
@login_required
def prescription_create(request, visit_pk):
    """Додати призначення до візиту."""
    from .forms import PrescriptionForm
    from .models import Prescription
    visit = get_object_or_404(
        Visit, pk=visit_pk, patient__client__organization=request.organization
    )
    if request.method == 'POST':
        form = PrescriptionForm(request.POST)
        if form.is_valid():
            rx = form.save(commit=False)
            rx.visit = visit
            rx.patient = visit.patient
            rx.save()
            messages.success(request, 'Призначення додано.')
            return redirect('clients:patient_detail', pk=visit.patient_id)
    else:
        form = PrescriptionForm()
    return render(request, 'clients/prescription_form.html', {
        'form': form, 'visit': visit, 'patient': visit.patient,
    })


@login_required
def prescription_delete(request, pk):
    """Видалити призначення."""
    from .models import Prescription
    rx = get_object_or_404(
        Prescription, pk=pk, patient__client__organization=request.organization
    )
    patient_pk = rx.patient_id
    if request.method == 'POST':
        rx.delete()
        messages.success(request, 'Призначення видалено.')
    return redirect('clients:patient_detail', pk=patient_pk)


# ── Документи CRUD ──────────────────────────────────────────────────────
@login_required
def document_upload(request, patient_pk):
    """Завантажити документ пацієнта."""
    from .forms import PatientDocumentForm
    from .models import PatientDocument
    patient = get_object_or_404(
        Patient, pk=patient_pk, client__organization=request.organization
    )
    # ?visit=<pk> — прийшли з картки прийому: знімок/УЗД чіпляємо саме до нього
    # і туди ж вертаємось (прохання Ірпеня 10.08).
    visit = None
    visit_pk = request.GET.get('visit') or request.POST.get('visit')
    if visit_pk:
        visit = Visit.objects.filter(pk=visit_pk, patient=patient).first()

    if request.method == 'POST':
        form = PatientDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.patient = patient
            doc.visit = visit
            doc.uploaded_by = request.user
            doc.save()
            messages.success(request, 'Документ завантажено.')
            if visit:
                return redirect('clients:visit_edit', pk=visit.pk)
            return redirect('clients:patient_detail', pk=patient_pk)
    else:
        initial = {}
        if visit:
            initial['date'] = timezone.localtime(visit.date).date()
        form = PatientDocumentForm(initial=initial)
    return render(request, 'clients/document_form.html', {
        'form': form, 'patient': patient, 'visit': visit,
    })


@login_required
def document_delete(request, pk):
    """Видалити документ."""
    from .models import PatientDocument
    doc = get_object_or_404(
        PatientDocument, pk=pk, patient__client__organization=request.organization
    )
    patient_pk = doc.patient_id
    visit_pk = doc.visit_id  # запам'ятати ДО видалення, щоб знати куди вертатись
    if request.method == 'POST':
        doc.file.delete(save=False)
        doc.delete()
        messages.success(request, 'Документ видалено.')
    if visit_pk:
        return redirect('clients:visit_edit', pk=visit_pk)
    return redirect('clients:patient_detail', pk=patient_pk)


# ── Шаблони візитів — API для JS ────────────────────────────────────────
def _plain_to_html(text):
    """Рядки з textarea → абзаци для редактора прийому.

    Якщо текст уже з розміткою (наш стартовий набір) — лишаємо як є.
    """
    from django.utils.html import escape
    text = (text or '').strip()
    if not text or '<' in text:
        return text
    return ''.join(f'<p>{escape(line.strip())}</p>' for line in text.splitlines())


@login_required
def visit_templates_json(request):
    """JSON список шаблонів візитів."""
    from .models import VisitTemplate
    templates = VisitTemplate.objects.filter(
        organization=request.organization, is_active=True
    ).order_by('name')
    return JsonResponse({'templates': [
        {
            'id': t.pk,
            'name': t.name,
            'complaint': t.complaint,
            'exam': t.exam,
            'diagnosis': t.diagnosis,
            'treatment': t.treatment,
            'notes': t.notes,
        }
        for t in templates
    ]})


@login_required
def visit_template_manage(request):
    """CRUD шаблонів візитів."""
    from .models import VisitTemplate
    from .forms import VisitTemplateForm
    org = request.organization
    templates = VisitTemplate.objects.filter(organization=org).order_by('name')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            form = VisitTemplateForm(request.POST, org=org)
            if form.is_valid():
                t = form.save(commit=False)
                t.organization = org
                # Текст із форми йде звичайними рядками, а в прийом його вставляє
                # редактор розмітки — без обгортки всі рядки злипаються в один.
                for field in ('complaint', 'exam', 'diagnosis', 'treatment', 'notes'):
                    setattr(t, field, _plain_to_html(getattr(t, field, '')))
                t.save()
                messages.success(request, f'Шаблон «{t.name}» створено.')
        elif action == 'delete':
            tpl_id = request.POST.get('template_id')
            VisitTemplate.objects.filter(pk=tpl_id, organization=org).delete()
            messages.success(request, 'Шаблон видалено.')
        return redirect('clients:visit_templates')

    form = VisitTemplateForm(org=org)
    return render(request, 'clients/visit_templates.html', {
        'templates': templates, 'form': form,
    })


@login_required
def audit_log_view(request):
    """Журнал аудиту змін медичних даних."""
    from .audit import AuditLog
    org = request.organization
    qs = AuditLog.objects.filter(organization=org).select_related('user').order_by('-created_at')

    # Фільтри
    content_type = request.GET.get('type', '')
    if content_type:
        qs = qs.filter(content_type=content_type)

    action = request.GET.get('action', '')
    if action:
        qs = qs.filter(action=action)

    from django.core.paginator import Paginator
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page', 1))

    types = AuditLog.objects.filter(organization=org).values_list('content_type', flat=True).distinct()

    return render(request, 'clients/audit_log.html', {
        'logs': page,
        'content_type': content_type,
        'action_filter': action,
        'types': types,
        'action_choices': AuditLog.Action.choices,
    })


@login_required
def audit_log_object(request, content_type, object_id):
    """Аудит конкретного об'єкта."""
    from .audit import AuditLog
    logs = AuditLog.objects.filter(
        content_type=content_type,
        object_id=object_id,
        organization=request.organization,
    ).select_related('user').order_by('-created_at')
    return render(request, 'clients/partials/audit_object.html', {
        'logs': logs,
        'content_type': content_type,
        'object_id': object_id,
    })


@login_required
def health_diary(request):
    """Щоденник здоров'я — список всіх опитувань."""
    from .models_health import HealthCheck
    from django.db.models import Q, Count
    from django.core.paginator import Paginator

    org = request.organization

    qs = HealthCheck.objects.filter(
        organization=org
    ).select_related('patient', 'patient__client').order_by('-sent_at')

    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)

    trigger = request.GET.get('trigger', '')
    if trigger:
        qs = qs.filter(trigger=trigger)

    paginator = Paginator(qs, 30)
    page = paginator.get_page(request.GET.get('page', 1))

    # Статистика
    stats = HealthCheck.objects.filter(organization=org).aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(status='pending')),
        ok=Count('id', filter=Q(status='ok')),
        concern=Count('id', filter=Q(status='concern')),
    )

    return render(request, 'clients/health_diary.html', {
        'checks': page,
        'status_filter': status,
        'trigger_filter': trigger,
        'stats': stats,
        'status_choices': HealthCheck.Status.choices,
        'trigger_choices': HealthCheck.Trigger.choices,
    })


@login_required
def ultrasound_create(request, patient_pk):
    """Створити протокол УЗД."""
    from .forms import UltrasoundForm
    from .models import UltrasoundReport
    patient = get_object_or_404(Patient, pk=patient_pk)
    org = request.organization
    default_doc = org.get_default_doctor(request.user) if org else request.user

    if request.method == 'POST':
        form = UltrasoundForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.patient = patient
            report.doctor = default_doc
            report.save()
            messages.success(request, 'Протокол УЗД збережено.')
            return redirect('clients:patient_detail', pk=patient_pk)
    else:
        from datetime import date
        form = UltrasoundForm(initial={'date': date.today()})

    return render(request, 'clients/ultrasound_form.html', {
        'form': form,
        'patient': patient,
    })


@login_required
def ultrasound_edit(request, pk):
    """Редагувати протокол УЗД."""
    from .forms import UltrasoundForm
    from .models import UltrasoundReport
    report = get_object_or_404(UltrasoundReport, pk=pk)

    if request.method == 'POST':
        form = UltrasoundForm(request.POST, instance=report)
        if form.is_valid():
            form.save()
            messages.success(request, 'Протокол оновлено.')
            return redirect('clients:patient_detail', pk=report.patient_id)
    else:
        form = UltrasoundForm(instance=report)

    return render(request, 'clients/ultrasound_form.html', {
        'form': form,
        'patient': report.patient,
        'report': report,
    })


@login_required
def ultrasound_pdf(request, pk):
    """PDF протокол УЗД."""
    from .models import UltrasoundReport
    report = get_object_or_404(
        UltrasoundReport, pk=pk, patient__client__organization=request.organization
    )

    from django.template.loader import render_to_string
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse('WeasyPrint не встановлено', status=500)

    html_string = render_to_string('clients/ultrasound_pdf.html', {
        'report': report,
        'patient': report.patient,
        'client': report.patient.client,
        'clinic': request.organization,
        'request': request,
    })
    pdf = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'filename="uzd-{report.patient.name}-{report.date}.pdf"'
    return response


@login_required
def ultrasound_delete(request, pk):
    """Видалити протокол УЗД."""
    from .models import UltrasoundReport
    report = get_object_or_404(UltrasoundReport, pk=pk)
    patient_pk = report.patient_id
    if request.method == 'POST':
        report.delete()
        messages.success(request, 'Протокол видалено.')
    return redirect('clients:patient_detail', pk=patient_pk)
