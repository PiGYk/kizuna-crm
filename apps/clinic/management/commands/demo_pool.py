# -*- coding: utf-8 -*-
"""Пул гостьових демо-клінік: тримати N вільних, прибирати старі зайняті."""
import secrets

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


def purge_org(org):
    """Повне видалення гостьової клініки з усіма даними.

    Organization.delete() саме по собі падає: частина звʼязків PROTECT
    (Client.organization, ExpenseCategory.organization), тому спершу
    прибираємо дані в порядку залежностей.
    """
    from django.contrib.auth import get_user_model
    from apps.clinic.tenant import org_context
    from apps.billing.models import Invoice
    from apps.appointments.models import Appointment
    from apps.clients.models import Client, Patient, Visit, Vaccine
    from apps.services.models import Service, ServiceCategory
    from apps.inventory.models import Product, StockMovement, Category as InvCat
    from apps.finance.models import Expense, CashOperation, Supplier, ExpenseCategory
    from apps.accounts.models_payroll import Shift

    User = get_user_model()

    org.default_doctor = None
    org.save(update_fields=['default_doctor'])

    # ⚡ Менеджери моделей тут tenant-aware: поза org_context вони віддають
    # порожні queryset-и, видалення «проходить» вхолосту, а потім org.delete()
    # падає на PROTECT. Тому вся чистка — всередині контексту клініки.
    with org_context(org):
        Invoice.objects.filter(organization=org).delete()
        Appointment.objects.filter(organization=org).delete()
        Visit.objects.filter(patient__client__organization=org).delete()
        Vaccine.objects.filter(patient__client__organization=org).delete()
        Patient.objects.filter(client__organization=org).delete()
        Client.objects.filter(organization=org).delete()
        StockMovement.objects.filter(product__organization=org).delete()
        Product.objects.filter(organization=org).delete()
        InvCat.objects.filter(organization=org).delete()
        Service.objects.filter(organization=org).delete()
        ServiceCategory.objects.filter(organization=org).delete()
        Expense.objects.filter(organization=org).delete()
        CashOperation.objects.filter(organization=org).delete()
        Supplier.objects.filter(organization=org).delete()
        ExpenseCategory.objects.filter(organization=org).delete()
        Shift.objects.filter(organization=org).delete()
        User.objects.filter(organization=org).delete()
    org.delete()


class Command(BaseCommand):
    help = 'Наповнити пул вільних демо-клінік і прибрати старі зайняті'

    def add_arguments(self, parser):
        parser.add_argument('--ensure', type=int, default=3,
                            help='скільки вільних клінік тримати напоготові')
        parser.add_argument('--cleanup-hours', type=int, default=24,
                            help='через скільки годин видаляти зайняту клініку')
        parser.add_argument('--purge-slug', default='',
                            help='видалити конкретну гостьову клініку за slug')

    def handle(self, *args, **opts):
        from apps.clinic.models import DemoTenant, Organization

        if opts.get('purge_slug'):
            org = Organization.objects.filter(slug=opts['purge_slug']).first()
            if org is None:
                self.stdout.write('клініки з таким slug немає')
                return
            DemoTenant.objects.filter(organization=org).delete()
            purge_org(org)
            self.stdout.write(self.style.SUCCESS(f"видалено {opts['purge_slug']}"))
            return

        # 1) прибрати зайняті, якими вже не користуються
        edge = timezone.now() - timedelta(hours=opts['cleanup_hours'])
        old = DemoTenant.objects.filter(taken_at__isnull=False, taken_at__lt=edge)
        killed = 0
        for t in old:
            org = t.organization
            t.delete()
            purge_org(org)
            killed += 1
        if killed:
            self.stdout.write(f'  прибрано зайнятих клінік: {killed}')

        # 2) догенерувати вільні до потрібної кількості
        free = DemoTenant.objects.filter(taken_at__isnull=True).count()
        need = max(0, opts['ensure'] - free)
        self.stdout.write(f'  вільних: {free}, треба догенерувати: {need}')

        for _ in range(need):
            token = secrets.token_hex(3)
            slug = f'demo-{token}'
            call_command('seed_demo', slug=slug, name='Демо-клініка')
            org = Organization.objects.filter(slug=slug).first()
            if org is None:
                self.stderr.write(f'  {slug}: клініку не створено, пропускаю')
                continue
            DemoTenant.objects.create(organization=org, username=f'demo_{token}')
            self.stdout.write(f'  + {slug}')

        total_free = DemoTenant.objects.filter(taken_at__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(f'пул готовий: вільних {total_free}'))
