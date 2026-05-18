from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, DetailView
from django.urls import reverse

from .forms import ServiceForm, ComponentFormSet
from .models import Service, ServiceCategory


class ServiceListView(LoginRequiredMixin, ListView):
    model = Service
    template_name = 'services/list.html'
    context_object_name = 'services'

    def get_queryset(self):
        qs = Service.objects.select_related('category').prefetch_related('components__product')
        if not self.request.GET.get('inactive'):
            qs = qs.filter(is_active=True)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        cat = self.request.GET.get('cat', '').strip()
        if cat == 'none':
            qs = qs.filter(category__isnull=True)
        elif cat.isdigit():
            qs = qs.filter(category_id=int(cat))
        return qs.order_by('category__sort_order', 'category__name', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '').strip()
        ctx['selected_cat'] = self.request.GET.get('cat', '').strip()
        ctx['categories'] = list(ServiceCategory.objects.all())

        # Згрупувати для рендеру за категорією
        groups = {}
        for s in ctx['services']:
            key = s.category.name if s.category else '— Без категорії —'
            groups.setdefault(key, []).append(s)
        cat_order = {c.name: c.sort_order for c in ctx['categories']}
        ctx['grouped_services'] = sorted(groups.items(), key=lambda kv: cat_order.get(kv[0], 9999))
        return ctx


class ServiceDetailView(LoginRequiredMixin, DetailView):
    model = Service
    template_name = 'services/detail.html'
    context_object_name = 'service'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['components'] = self.object.components.select_related('product__unit')
        return ctx


@login_required
def service_create(request):
    form = ServiceForm(request.POST or None)
    formset = ComponentFormSet(request.POST or None, prefix='comp')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        service = form.save(commit=False)
        service.organization = request.organization
        service.save()
        formset.instance = service
        formset.save()
        messages.success(request, 'Послугу додано')
        return redirect('services:edit', pk=service.pk)
    return render(request, 'services/form.html', {'form': form, 'formset': formset})


@login_required
def service_update(request, pk):
    service = get_object_or_404(Service, pk=pk, organization=request.organization)
    form = ServiceForm(request.POST or None, instance=service)
    formset = ComponentFormSet(request.POST or None, instance=service, prefix='comp')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        form.save()
        formset.save()
        messages.success(request, 'Збережено')
        return redirect('services:edit', pk=service.pk)
    return render(request, 'services/form.html', {'form': form, 'formset': formset, 'service': service})


@login_required
def service_delete(request, pk):
    service = get_object_or_404(Service, pk=pk, organization=request.organization)
    if request.method == 'POST':
        service.delete()
        messages.success(request, 'Послугу видалено')
        return redirect('services:list')
    return redirect('services:edit', pk=pk)
