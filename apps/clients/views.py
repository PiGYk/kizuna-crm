from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy, reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required

from .forms import ClientForm, PatientForm, VisitForm, VaccineForm
from .models import Client, Patient, Visit, Vaccine


class ClientListView(LoginRequiredMixin, ListView):
    model = Client
    template_name = 'clients/list.html'
    context_object_name = 'clients'
    paginate_by = 30

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('patients')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(phone__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        return ctx


class ClientCreateView(LoginRequiredMixin, CreateView):
    model = Client
    form_class = ClientForm
    template_name = 'clients/form.html'

    def get_success_url(self):
        return reverse('clients:detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Клієнта додано')
        return super().form_valid(form)


class ClientUpdateView(LoginRequiredMixin, UpdateView):
    model = Client
    form_class = ClientForm
    template_name = 'clients/form.html'

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
    form = PatientForm(request.POST or None, request.FILES or None)
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
    form = PatientForm(request.POST or None, request.FILES or None, instance=patient)
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
        ctx = super().get_context_data(**kwargs)
        ctx['visits'] = self.object.visits.select_related('doctor').all()
        ctx['vaccines'] = self.object.vaccines.select_related('doctor').all()
        ctx['visit_form'] = VisitForm(initial={'doctor': self.request.user})
        ctx['vaccine_form'] = VaccineForm(initial={'doctor': self.request.user})
        return ctx


@login_required
def visit_create(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    form = VisitForm(request.POST or None, initial={'doctor': request.user})
    if request.method == 'POST' and form.is_valid():
        visit = form.save(commit=False)
        visit.patient = patient
        visit.save()
        messages.success(request, 'Візит додано')
        return redirect('clients:patient_detail', pk=patient.pk)
    return render(request, 'clients/visit_form.html', {'form': form, 'patient': patient})


@login_required
def visit_update(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    form = VisitForm(request.POST or None, instance=visit)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Збережено')
        return redirect('clients:patient_detail', pk=visit.patient.pk)
    return render(request, 'clients/visit_form.html', {'form': form, 'patient': visit.patient, 'visit': visit})


@login_required
def vaccine_create(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    form = VaccineForm(request.POST or None, initial={'doctor': request.user})
    if request.method == 'POST' and form.is_valid():
        vaccine = form.save(commit=False)
        vaccine.patient = patient
        vaccine.save()
        messages.success(request, 'Вакцинацію додано')
        return redirect('clients:patient_detail', pk=patient.pk)
    return render(request, 'clients/vaccine_form.html', {'form': form, 'patient': patient})


@login_required
def vaccine_update(request, pk):
    vaccine = get_object_or_404(Vaccine, pk=pk)
    form = VaccineForm(request.POST or None, instance=vaccine)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Збережено')
        return redirect('clients:patient_detail', pk=vaccine.patient.pk)
    return render(request, 'clients/vaccine_form.html', {'form': form, 'patient': vaccine.patient, 'vaccine': vaccine})


# HTMX live search — повертає partial з результатами
@login_required
def client_search(request):
    q = request.GET.get('q', '').strip()
    clients = []
    if len(q) >= 2:
        clients = Client.objects.filter(
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(phone__icontains=q)
        ).prefetch_related('patients')[:10]
    return render(request, 'clients/partials/search_results.html', {'clients': clients, 'q': q})
