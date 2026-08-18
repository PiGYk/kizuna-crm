"""
seed_demo — заповнює / оновлює демо-тенант «Ветклініка «Лапка»»
реалістичними даними для скріншотів і публічного демо-акаунта.

Запуск:
  docker compose exec -T web python manage.py seed_demo
  docker compose exec -T web python manage.py seed_demo --reset

БЕЗПЕКА:
  - org.telegram_bot_token = '' → Telegram-розсилки інертні
  - org.checkbox_license_key = '' → фіскалізація не відправляється
  - org.bot_base_url = '' → PDF через бота не генерується
  - demo-юзер: is_staff=False, is_superuser=False
"""

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

RNG = random.Random(42)
User = None  # ініціалізується в handle() після Django setup

# ─── Константи дат ────────────────────────────────────────────────
TODAY = date.today()
SIX_MONTHS_AGO = TODAY - timedelta(days=182)
TWO_WEEKS_AHEAD = TODAY + timedelta(days=14)

# ─── Дані — імена ─────────────────────────────────────────────────
FIRST_M = ['Тарас', 'Ігор', 'Максим', 'Олексій', 'Богдан', 'Дмитро',
           'Василь', 'Сергій', 'Андрій', 'Юрій', 'Михайло', 'Роман',
           'Петро', 'Владислав', 'Євген', 'Олег', 'Руслан', 'Вадим',
           'Назар', 'Ярослав', 'Іван', 'Артем', 'Денис', 'Артур']
FIRST_F = ['Марина', 'Оксана', 'Тетяна', 'Людмила', 'Ганна', 'Катерина',
           'Олена', 'Наталія', 'Ірина', 'Юлія', 'Олеся', 'Вікторія',
           'Аліна', 'Дарина', 'Соломія', 'Яна', 'Лариса', 'Надія',
           'Уляна', 'Леся', 'Мирослава', 'Христина', 'Поліна', 'Лілія']
LAST_NAMES = [
    'Олійник', 'Шевченко', 'Бойко', 'Поліщук', 'Коваленко', 'Мельник',
    'Лисенко', 'Кравченко', 'Гнатенко', 'Савченко', 'Ткаченко', 'Гриценко',
    'Романенко', 'Марченко', 'Харченко', 'Данченко', 'Гончаренко', 'Петренко',
    'Тимченко', 'Бондаренко', 'Іваненко', 'Павленко', 'Зайченко', 'Власенко',
    'Коломієць', 'Дяченко', 'Семененко', 'Яценко', 'Козаченко', 'Стець',
    'Лукяненко', 'Пономаренко', 'Остапенко', 'Даниленко', 'Антоненко',
    'Волощук', 'Мазуренко', 'Кириленко', 'Білик', 'Гладченко',
    'Нечипоренко', 'Бабенко', 'Василенко', 'Захаренко', 'Корж',
    'Мороз', 'Хоменко', 'Купрієнко', 'Пилипенко', 'Тищенко',
]
DOG_BREEDS = [
    'Лабрадор', 'Золотистий ретривер', 'Овчарка німецька', 'Мопс',
    'Такса', 'Бульдог французький', 'Шпіц', 'Чихуахуа', 'Хаскі', 'Бігль',
    'Корги', 'Далматинець', 'Мальтезе', 'Кавказька вівчарка', 'Бордер коллі',
    'Йоркширський тер`єр', 'Боксер', 'Доберман', 'Самоєд', 'Сенбернар',
]
CAT_BREEDS = [
    'Шотландська вислоуха', 'Британська короткошерста', 'Мейн-кун',
    'Сіамська', 'Перська', 'Бенгальська', 'Сфінкс', 'Руська блакитна',
    'Метис', 'Безпородна', 'Абіссінська', 'Норвезька лісова',
]
DOG_NAMES = ['Рекс', 'Дружок', 'Бобік', 'Зефір', 'Тедді', 'Луна', 'Ріта',
             'Ніка', 'Барні', 'Чарлі', 'Белла', 'Нора', 'Ельза', 'Арчі',
             'Бакс', 'Грей', 'Снупі', 'Лорд', 'Жак', 'Еді', 'Боні', 'Льоша']
CAT_NAMES = ['Мурчик', 'Сімба', 'Пушок', 'Тиграня', 'Лапочка', 'Масик',
             'Муся', 'Барсик', 'Кеді', 'Снєжок', 'Котик', 'Ромео', 'Стрілка',
             'Нюся', 'Персик', 'Лунтик', 'Феня', 'Крапля']
OTHER_NAMES = ['Пушок', 'Малюк', 'Піна', 'Горіх', 'Буся', 'Кулька', 'Рябчик']

DIAGNOSES_TREATMENT = [
    ('Гастроентерит', 'Блювота, відмова від їжі', 'Дієта, Метоклопрамід 0.5 мл, Ентеросгель'),
    ('Отит зовнішній', 'Чеше вуха, неприємний запах', 'Промивання, Отодепін краплі 7 днів'),
    ('Алергічна дерматологія', 'Свербіж, лущення шкіри', 'Апоквел 5.4 мг, гіпоалергенна дієта'),
    ('Пародонтит', 'Неприємний запах з рота, жовтий наліт', 'Ультразвукова чистка, Дентавєдін гель'),
    ('Цистит', 'Часте сечовипускання, поскулює', 'Байтрил 2.5% 0.4 мл, Котервін 2 тижні'),
    ('Кон\'юнктивіт', 'Виділення з очей', 'Тобрекс краплі 3 рази на день, 7 днів'),
    ('Піодермія', 'Гнійники на шкірі, облизує лапу', 'Цефалексин 20 мг/кг, шампунь Хлоргексидин'),
    ('Гельмінтоз', 'Схуд, апетит збережений', 'Мільбемакс 1 таб, повторно через 14 днів'),
    ('Артрит', 'Кульгавість на ліву передню лапу', 'Локсиком 0.2 мг/кг, обмеження навантаження'),
    ('Новоутворення підшкірне', 'Грудка в районі паху', 'Видалення новоутворення, гістологія'),
    ('Анемія', 'Бліді слизові, млявість', 'Феросан 1 мл/добу, корекція раціону'),
    ('Профілактичний огляд', 'Плановий прийом', 'Норма. Рекомендовано щорічне щеплення'),
    ('Респіраторна інфекція', 'Чхання, виділення з носа', 'Байтрил 2.5%, Дексаметазон 0.1 мл'),
    ('Стресова анорексія', 'Відмова від їжі після переїзду', 'Ципрогептадин, Нутрі-Кал стимуляція'),
    ('Вивих суглоба', 'Накульгує, тримає лапу', 'Ручне вправлення під седацією, шина'),
]

COMPLAINT_NOTES = [
    'Не їсть другу добу, апатичний',
    'Кривавий стілець, блювота',
    'Різко схуд, п\'є багато води',
    'Планова вакцинація',
    'Тремтить, температура',
    'Пасивний після прогулянки',
    'Набряк на лапі',
    'Не може нормально жувати',
    'Надмірне облизування лап',
]


class Command(BaseCommand):
    help = 'Seed demo organization "Ветклініка «Лапка»"'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Видалити всі дані демо-тенанта і наповнити заново',
        )
        parser.add_argument(
            '--slug', default='demo',
            help='slug тенанта (для пулу гостьових демо: demo-xxxx)',
        )
        parser.add_argument(
            '--name', default='',
            help='назва клініки (за замовчуванням — Ветклініка «Лапка»)',
        )

    def handle(self, *args, **options):
        global User
        User = get_user_model()
        from apps.clinic.models import Organization
        from apps.clinic.tenant import org_context

        self.stdout.write('=== seed_demo: старт ===')

        self.slug = options.get('slug') or 'demo'
        # суфікс логінів: логіни в системі глобально унікальні, тому
        # кожна гостьова клініка мусить мати свої (інакше юзер
        # «переїде» в новий тенант і зламає попередній).
        self.usuffix = '' if self.slug == 'demo' else '_' + self.slug.replace('demo-', '')
        org = self._get_or_create_org(self.slug, options.get('name') or '')

        if options['reset']:
            self.stdout.write('  --reset: видаляємо старі дані демо-тенанта...')
            with org_context(org):
                self._delete_demo_data(org)
            self.stdout.write('  Старі дані видалено.')

        with org_context(org):
            # Перевірка: якщо вже є дані — не дублюємо
            from apps.clients.models import Client
            if not options['reset'] and Client.objects.filter(organization=org).count() > 10:
                self.stdout.write(self.style.WARNING(
                    '  Демо вже наповнено. Запустіть з --reset щоб скинути.'
                ))
                return

            staff = self._seed_users(org)
            services, svc_cats = self._seed_services(org)
            products, suppliers = self._seed_inventory(org, staff['admin'])
            clients = self._seed_clients(org)
            patients = self._seed_patients(org, clients, staff['doctors'])
            self._seed_vaccines(patients, staff['doctors'])
            appointments = self._seed_appointments(org, clients, patients, staff['doctors'], services)
            self._seed_visits(patients, staff['doctors'])
            self._seed_invoices(org, clients, patients, staff['doctors'], services)
            self._seed_expenses(org, staff['admin'])
            self._seed_shifts(org, staff['doctors'] + [staff['assistant']])

            # Встановлюємо default_doctor
            org.default_doctor = staff['doctors'][0]
            org.save(update_fields=['default_doctor'])

            self._print_summary(org)

        self.stdout.write(self.style.SUCCESS('=== seed_demo: завершено ==='))

    # ─────────────────────────────────────────────────────────────────
    # ORG
    # ─────────────────────────────────────────────────────────────────

    def _get_or_create_org(self, slug='demo', name=''):
        from apps.clinic.models import Organization

        org, created = Organization.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name or 'Ветклініка «Лапка»',
                'short_name': 'Лапка (ДЕМО)',
                'is_active': True,
                'trial_expires_at': timezone.make_aware(datetime(2099, 12, 31)),
                'address': 'вул. Хрещатик, 22, Київ, 01001',
                'phone': '+38 (044) 000-11-22',
                'email': 'demo@lapka.vet',
                'work_hours': 'Пн–Сб 09:00–19:00',
                'website': 'https://lapka.vet',
                'currency_symbol': '₴',
                'work_days': [0, 1, 2, 3, 4, 5],
                'work_start': time(9, 0),
                'work_end': time(19, 0),
                'slot_duration': 30,
                'primary_color': '#DEAA01',
                'sidebar_color': '#12100F',
                'telegram_bot_token': '',
                'checkbox_license_key': '',
                'checkbox_pin': '',
                'bot_base_url': '',
                'webhook_secret': '',
                'plan': 'clinic',
            }
        )
        if not created:
            org.is_active = True
            org.trial_expires_at = timezone.make_aware(datetime(2099, 12, 31))
            org.telegram_bot_token = ''
            org.checkbox_license_key = ''
            org.checkbox_pin = ''
            org.bot_base_url = ''
            org.save()

        self.stdout.write(f'  Org id={org.pk} {"створено" if created else "існує"}')
        return org

    def _delete_demo_data(self, org):
        from apps.billing.models import Invoice
        from apps.appointments.models import Appointment
        from apps.clients.models import Client, Patient, Visit, Vaccine
        from apps.services.models import Service, ServiceCategory
        from apps.inventory.models import Product, StockMovement, Category as InvCat
        from apps.finance.models import Expense, CashOperation, Supplier, ExpenseCategory
        from apps.accounts.models_payroll import Shift

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
        User.objects.filter(organization=org).exclude(username='demo' + self.usuffix).delete()

    # ─────────────────────────────────────────────────────────────────
    # USERS
    # ─────────────────────────────────────────────────────────────────

    def _seed_users(self, org):
        doctors_data = [
            {'username': 'lapka_dr1', 'first_name': 'Олена', 'last_name': 'Кравченко',
             'email': 'kravchenko@lapka.vet', 'role': 'doctor',
             'salary_type': 'percent', 'salary_percent': Decimal('15')},
            {'username': 'lapka_dr2', 'first_name': 'Максим', 'last_name': 'Тимченко',
             'email': 'tymchenko@lapka.vet', 'role': 'doctor',
             'salary_type': 'percent', 'salary_percent': Decimal('12')},
            {'username': 'lapka_dr3', 'first_name': 'Наталія', 'last_name': 'Бондаренко',
             'email': 'bondarenko@lapka.vet', 'role': 'doctor',
             'salary_type': 'fixed', 'salary_fixed': Decimal('25000')},
        ]
        asst_data = {
            'username': 'lapka_asst', 'first_name': 'Аліна', 'last_name': 'Петрук',
            'email': 'petruk@lapka.vet', 'role': 'assistant',
            'salary_type': 'fixed', 'salary_fixed': Decimal('18000'),
        }

        # Demo admin
        demo, _ = User.objects.get_or_create(
            username='demo' + self.usuffix,
            defaults={
                'first_name': 'Демо', 'last_name': 'Адмін',
                'email': 'demo@lapka.vet',
                'role': 'admin', 'organization': org,
                'is_staff': False, 'is_superuser': False,
            }
        )
        demo.set_password('demo12345')
        demo.organization = org
        demo.save()

        doctors = []
        for d in doctors_data:
            u, _ = User.objects.get_or_create(
                username=d['username'] + self.usuffix,
                defaults={
                    'first_name': d['first_name'], 'last_name': d['last_name'],
                    'email': d['email'], 'role': d['role'], 'organization': org,
                    'salary_type': d['salary_type'],
                    'salary_percent': d.get('salary_percent', Decimal('0')),
                    'salary_fixed': d.get('salary_fixed', Decimal('0')),
                    'is_staff': False, 'is_superuser': False,
                }
            )
            u.organization = org
            u.save(update_fields=['organization'])
            doctors.append(u)

        asst, _ = User.objects.get_or_create(
            username=asst_data['username'] + self.usuffix,
            defaults={
                'first_name': asst_data['first_name'], 'last_name': asst_data['last_name'],
                'email': asst_data['email'], 'role': asst_data['role'], 'organization': org,
                'salary_type': asst_data['salary_type'],
                'salary_fixed': asst_data['salary_fixed'],
                'is_staff': False, 'is_superuser': False,
            }
        )
        asst.organization = org
        asst.save(update_fields=['organization'])

        self.stdout.write(f'  Users: demo + {len(doctors)} лікарів + 1 асистент')
        return {'admin': demo, 'doctors': doctors, 'assistant': asst}

    # ─────────────────────────────────────────────────────────────────
    # SERVICES
    # ─────────────────────────────────────────────────────────────────

    def _seed_services(self, org):
        from apps.services.models import ServiceCategory, Service

        cats_data = [
            ('Консультація', 0, [
                ('Первинний прийом', 280),
                ('Повторний прийом', 200),
                ('Онлайн-консультація', 160),
                ('Профілактичний огляд', 180),
            ]),
            ('Вакцинація', 1, [
                ('Nobivac DHPPi (чума, гепатит, паровірус)', 380),
                ('Nobivac Rabies (сказ)', 290),
                ('Nobivac RL (лептоспіроз)', 320),
                ('Феліген CRP (котячий нежить, панлейкопенія)', 420),
                ('Комплексне щеплення Квадрикат', 680),
            ]),
            ('Хірургія', 2, [
                ('Стерилізація кішки (OHE)', 2600),
                ('Кастрація кота', 1900),
                ('Стерилізація суки', 3800),
                ('Кастрація пса', 2400),
                ('Видалення новоутворення', 2200),
                ('Операція на кишківнику', 5500),
            ]),
            ('Стоматологія', 3, [
                ('УЗ-чистка зубів', 1300),
                ('Видалення зуба', 650),
                ('Поліровка зубів', 450),
                ('Зовнішній огляд ротової порожнини', 150),
            ]),
            ('УЗД / Рентген', 4, [
                ('УЗД органів черевної порожнини', 680),
                ('УЗД серця (ЕхоКГ)', 900),
                ('Рентген (1 проєкція)', 480),
                ('Рентген (2 проєкції)', 720),
            ]),
            ('Лабораторія', 5, [
                ('Загальний аналіз крові', 380),
                ('Біохімічний аналіз крові', 680),
                ('Аналіз сечі загальний', 260),
                ('Цитологія (мазок)', 850),
                ('Паразитологія (кал)', 220),
            ]),
            ('Грумінг', 6, [
                ('Купання та сушка', 380),
                ('Стрижка (стандарт)', 650),
                ('Стрижка кігтів', 160),
                ('Чищення вух', 120),
                ('Анальні залози', 130),
            ]),
            ('Стаціонар', 7, [
                ('Добове утримання (кат. А)', 420),
                ('Крапельниця в/в', 380),
                ('Ін\'єкція підшкірна/в/м', 90),
                ('Оксигенотерапія (год)', 220),
            ]),
        ]

        all_services = []
        all_cats = []
        for cat_name, sort_order, svcs in cats_data:
            cat, _ = ServiceCategory.objects.get_or_create(
                name=cat_name, organization=org,
                defaults={'sort_order': sort_order}
            )
            all_cats.append(cat)
            for svc_name, price in svcs:
                svc, _ = Service.objects.get_or_create(
                    name=svc_name, organization=org,
                    defaults={
                        'price': Decimal(str(price)),
                        'category': cat,
                        'is_active': True,
                        'show_on_website': True,
                    }
                )
                all_services.append(svc)

        self.stdout.write(f'  Services: {len(all_services)} у {len(all_cats)} категоріях')
        return all_services, all_cats

    # ─────────────────────────────────────────────────────────────────
    # INVENTORY
    # ─────────────────────────────────────────────────────────────────

    def _seed_inventory(self, org, admin_user):
        from apps.inventory.models import Category as InvCat, Product, StockMovement
        from apps.finance.models import Supplier
        from django.db.models import F

        # Одиниці виміру — використовуємо глобальні (organization_id IS NULL)
        from apps.inventory.models import Unit
        unit_ml  = Unit.objects.filter(short='мл', organization__isnull=True).first()
        unit_tab = Unit.objects.filter(short='таб', organization__isnull=True).first()
        unit_shт = Unit.objects.filter(short='шт', organization__isnull=True).first()
        unit_up  = Unit.objects.filter(short='уп', organization__isnull=True).first()
        unit_amp = Unit.objects.filter(short='амп', organization__isnull=True).first()
        unit_kg  = Unit.objects.filter(short='кг', organization__isnull=True).first()

        # Постачальники
        suppliers_data = [
            ('ТОВ «ВетФарм Україна»', 'Юлія Гаврилова', '+38 (044) 200-11-33', 'order@vetfarm.ua'),
            ('ФОП Ляска О.І.', 'Олексій Ляска', '+38 (067) 345-67-89', 'lyaska@vetopt.com'),
            ('СвітФарм ТОВ', 'Ірина Мороз', '+38 (050) 234-56-78', 'info@svitfarm.ua'),
        ]
        suppliers = []
        for s_name, s_contact, s_phone, s_email in suppliers_data:
            s, _ = Supplier.objects.get_or_create(
                name=s_name, organization=org,
                defaults={'contact_person': s_contact, 'phone': s_phone, 'email': s_email}
            )
            suppliers.append(s)

        # Категорії складу
        cats = {}
        for c in ['Ін\'єкційні препарати', 'Вакцини', 'Антибіотики', 'Таблетки та капсули',
                  'Витратні матеріали', 'Засоби від паразитів', 'Дезінфекція', 'Корм та добавки']:
            cats[c], _ = InvCat.objects.get_or_create(name=c, organization=org)

        products_data = [
            # (name, cat, unit, buy, sell, qty, min_qty, expiry_offset_days)
            ('Пропофол 1% 20 мл',            'Ін\'єкційні препарати', unit_ml,  38, 85, 45, 10, 180),
            ('Кетамін 5% 10 мл',             'Ін\'єкційні препарати', unit_ml,  22, 50, 60, 15, 365),
            ('Буторфанол 1% 10 мл',          'Ін\'єкційні препарати', unit_ml,  45, 95, 30, 8,  180),
            ('Дексаметазон 0.4% 1 мл',       'Ін\'єкційні препарати', unit_amp, 12, 28, 80, 20, 270),
            ('Р-р Рінгера 500 мл',           'Ін\'єкційні препарати', unit_ml,  28, 55, 120, 30, 365),
            ('Натрію хлорид 0.9% 500 мл',   'Ін\'єкційні препарати', unit_ml,  24, 48, 90, 25, 365),
            ('Метоклопрамід 5 мг/мл 2 мл',  'Ін\'єкційні препарати', unit_amp, 8,  20, 50, 15, 270),
            ('Гамавіт 2 мл',                 'Ін\'єкційні препарати', unit_amp, 18, 40, 60, 15, 270),
            ('Байтрил 2.5% 100 мл',          'Антибіотики',           unit_ml,  85, 180, 35, 8,  270),
            ('Синулокс 50 мг таб N10',       'Антибіотики',           unit_tab, 62, 140, 80, 20, 365),
            ('Амоксицилін 15% 100 мл',       'Антибіотики',           unit_ml,  70, 150, 25, 6,  180),
            ('Цефалексин 250 мг таб N20',    'Антибіотики',           unit_tab, 45, 95, 60, 15, 365),
            ('Nobivac DHPPi (флакон)',        'Вакцини',               unit_shт, 85, 380, 20, 5,  180),
            ('Nobivac Rabies 1 мл',          'Вакцини',               unit_shт, 65, 290, 15, 4,  180),
            ('Феліген CRP (набір)',           'Вакцини',               unit_shт, 95, 420, 12, 3,  180),
            ('Nobivac RL (флакон)',           'Вакцини',               unit_shт, 78, 320, 10, 3,  180),
            ('Мільбемакс для котів',         'Засоби від паразитів',  unit_tab, 55, 130, 40, 10, 365),
            ('Мільбемакс для собак',         'Засоби від паразитів',  unit_tab, 65, 150, 35, 10, 365),
            ('Бравекто (250–500 мг)',         'Засоби від паразитів',  unit_tab, 280, 620, 15, 4,  365),
            ('Фронтлайн спрей 100 мл',       'Засоби від паразитів',  unit_ml,  120, 260, 20, 5,  365),
            ('Інсектал краплі 0.5 мл',       'Засоби від паразитів',  unit_shт, 35, 80, 30, 8,  365),
            ('Шприц 5 мл (уп. 100 шт)',      'Витратні матеріали',    unit_up,  45, 95, 8, 2,  None),
            ('Шприц 2 мл (уп. 100 шт)',      'Витратні матеріали',    unit_up,  38, 80, 10, 3,  None),
            ('Голка 0.8×40 (уп. 100 шт)',    'Витратні матеріали',    unit_up,  28, 60, 12, 3,  None),
            ('Рукавички латексні (уп.100)',  'Витратні матеріали',    unit_up,  55, 110, 15, 4,  None),
            ('Бинт марлевий 10 см',          'Витратні матеріали',    unit_shт, 8,  18, 50, 15, None),
            ('Хлоргексидин 0.05% 500 мл',    'Дезінфекція',           unit_ml,  22, 45, 20, 5,  365),
            ('Лектрин ФОРТЕ дез.засіб 1 л', 'Дезінфекція',           unit_ml,  85, 160, 5, 2,  365),
            ('Пантотен вет. краплі 30 мл',   'Корм та добавки',       unit_ml,  60, 130, 25, 6,  365),
            ('Нутрі-Кал паста 120 г',        'Корм та добавки',       unit_shт, 95, 200, 12, 3,  365),
            # Кілька зі ЗНИЖЕНИМ залишком для екрану "Що замовити"
            ('Телазол 100 мг',               'Ін\'єкційні препарати', unit_shт, 280, 580, 2, 5,  270),
            ('Ізофлуран 250 мл',             'Ін\'єкційні препарати', unit_ml,  480, 980, 3, 8,  365),
            ('Котервін 30 мл',               'Засоби від паразитів',  unit_ml,  38, 80, 2, 5,  365),
        ]

        all_products = []
        supplier_cycle = suppliers * 20
        for i, (name, cat_name, unit, buy, sell, qty, min_qty, exp_offset) in enumerate(products_data):
            if unit is None:
                unit = unit_shт

            exp_date = None
            if exp_offset:
                exp_date = TODAY + timedelta(days=exp_offset + RNG.randint(-30, 60))

            prod, created = Product.objects.get_or_create(
                name=name, organization=org,
                defaults={
                    'category': cats.get(cat_name),
                    'unit': unit,
                    'buy_price': Decimal(str(buy)),
                    'sell_price': Decimal(str(sell)),
                    'quantity': Decimal('0'),
                    'min_quantity': Decimal(str(min_qty)),
                    'is_active': True,
                    'expiry_date': exp_date,
                    'sku': '',
                    'notes': '',
                }
            )
            all_products.append(prod)

            if created and qty > 0:
                # Прихід (оновлює quantity автоматично через StockMovement.save)
                sm = StockMovement.objects.create(
                    product=prod,
                    type='in',
                    quantity=Decimal(str(qty)),
                    price=Decimal(str(buy)),
                    supplier=supplier_cycle[i],
                    reason='Початковий залишок (seed)',
                    created_by=admin_user,
                )
                # Backdating: 5-7 місяців тому
                sm_date = timezone.now() - timedelta(days=RNG.randint(150, 200))
                StockMovement.objects.filter(pk=sm.pk).update(created_at=sm_date)

        self.stdout.write(f'  Inventory: {len(all_products)} товарів, {len(suppliers)} постачальників')
        return all_products, suppliers

    # ─────────────────────────────────────────────────────────────────
    # CLIENTS
    # ─────────────────────────────────────────────────────────────────

    def _seed_clients(self, org):
        from apps.clients.models import Client

        notes_pool = [
            'Просить нагадувати про щеплення', 'Надає перевагу ранковим прийомам',
            'Алергія на пеніцилін (власник)', '', '', '', '', '',
        ]

        clients = []
        last_names = RNG.sample(LAST_NAMES, len(LAST_NAMES))
        for i in range(75):
            is_female = RNG.random() > 0.45
            fn_pool = FIRST_F if is_female else FIRST_M
            first = fn_pool[i % len(fn_pool)]
            last = last_names[i % len(last_names)]
            phone = f'+38 (0{RNG.choice(["99","98","97","96","93"])}) {RNG.randint(100,999)}-{RNG.randint(10,99)}-{RNG.randint(10,99)}'
            discount = Decimal(str(RNG.choice([0, 0, 0, 0, 5, 5, 10, 15])))
            note = RNG.choice(notes_pool)

            c, _ = Client.objects.get_or_create(
                first_name=first, last_name=last, organization=org,
                defaults={
                    'phone': phone,
                    'email': f'{last.lower().replace("\'", "")}{i}@email.ua' if RNG.random() > 0.4 else '',
                    'discount_percent': discount,
                    'notes': note,
                }
            )
            clients.append(c)

        self.stdout.write(f'  Clients: {len(clients)}')
        return clients

    # ─────────────────────────────────────────────────────────────────
    # PATIENTS
    # ─────────────────────────────────────────────────────────────────

    def _seed_patients(self, org, clients, doctors):
        from apps.clients.models import Patient

        patients = []
        for i, client in enumerate(clients):
            # 1-2 тварини на клієнта, деякі мають 3
            count = RNG.choices([1, 1, 2, 3], weights=[40, 30, 20, 10])[0]
            for j in range(count):
                species = RNG.choices(
                    ['dog', 'cat', 'rabbit', 'bird', 'hamster'],
                    weights=[45, 40, 7, 5, 3]
                )[0]

                if species == 'dog':
                    name = RNG.choice(DOG_NAMES)
                    breed = RNG.choice(DOG_BREEDS)
                elif species == 'cat':
                    name = RNG.choice(CAT_NAMES)
                    breed = RNG.choice(CAT_BREEDS)
                else:
                    name = RNG.choice(OTHER_NAMES)
                    breed = ''

                sex = RNG.choice(['male', 'female', 'unknown'])
                dob = TODAY - timedelta(days=RNG.randint(180, 365 * 14))
                weight = Decimal(str(round(RNG.uniform(0.5, 45.0), 1)))
                is_neutered = RNG.random() > 0.55
                is_archived = j == count - 1 and RNG.random() > 0.88 and count > 1

                p, _ = Patient.objects.get_or_create(
                    name=name, client=client,
                    defaults={
                        'species': species,
                        'breed': breed,
                        'sex': sex,
                        'date_of_birth': dob,
                        'is_neutered': is_neutered,
                        'is_archived': is_archived,
                        'assigned_doctor': RNG.choice(doctors),
                        'notes': '',
                        'allergies': RNG.choice(['', '', '', 'Алергія на пеніцилін', 'Непереносимість кетаміну']),
                    }
                )
                patients.append(p)

        self.stdout.write(f'  Patients: {len(patients)}')
        return patients

    # ─────────────────────────────────────────────────────────────────
    # VACCINES
    # ─────────────────────────────────────────────────────────────────

    def _seed_vaccines(self, patients, doctors):
        from apps.clients.models import Vaccine

        vax_names = {
            'dog': ['Nobivac DHPPi', 'Nobivac Rabies', 'Nobivac RL', 'Квадрикат'],
            'cat': ['Феліген CRP', 'Пуревакс RCPCh', 'Nobivac Rabies'],
            'other': ['Nobivac Rabies'],
        }
        count = 0
        for p in RNG.sample(patients, min(70, len(patients))):
            species_key = p.species if p.species in vax_names else 'other'
            vax = RNG.choice(vax_names[species_key])
            vax_date = TODAY - timedelta(days=RNG.randint(30, 300))
            next_date = vax_date + timedelta(days=365)

            if not Vaccine.objects.filter(patient=p, name=vax).exists():
                Vaccine.objects.create(
                    patient=p,
                    doctor=RNG.choice(doctors),
                    name=vax,
                    date=vax_date,
                    next_date=next_date,
                    valid_until=next_date,
                    batch_number=f'LOT-{RNG.randint(100000, 999999)}',
                )
                count += 1
        self.stdout.write(f'  Vaccines: {count}')

    # ─────────────────────────────────────────────────────────────────
    # APPOINTMENTS
    # ─────────────────────────────────────────────────────────────────

    def _seed_appointments(self, org, clients, patients, doctors, services):
        from apps.appointments.models import Appointment

        appointments = []

        # Минулі (3 місяці, completed/cancelled)
        for day_offset in range(90, 0, -1):
            appt_date = TODAY - timedelta(days=day_offset)
            if appt_date.weekday() == 6:  # неділя — вихідний
                continue
            n_today = RNG.randint(5, 12)
            for slot in range(n_today):
                hour = 9 + slot
                if hour >= 18:
                    break
                client = RNG.choice(clients)
                patient_qs = [p for p in patients if p.client_id == client.id and not p.is_archived]
                if not patient_qs:
                    patient_qs = patients[:3]
                patient = RNG.choice(patient_qs)
                status = RNG.choices(['completed', 'completed', 'completed', 'cancelled', 'no_show'],
                                     weights=[60, 15, 10, 10, 5])[0]
                dt = timezone.make_aware(datetime(appt_date.year, appt_date.month, appt_date.day,
                                                   hour, RNG.choice([0, 30])))
                a = Appointment(
                    client=client, patient=patient,
                    doctor=RNG.choice(doctors),
                    starts_at=dt,
                    duration=RNG.choice([30, 30, 30, 60, 90]),
                    status=status,
                    organization=org,
                    created_by=RNG.choice(doctors),
                    notes=RNG.choice(['', '', RNG.choice(COMPLAINT_NOTES)]),
                )
                appointments.append(a)

        # Майбутні (2 тижні, confirmed/scheduled)
        for day_offset in range(0, 15):
            appt_date = TODAY + timedelta(days=day_offset)
            if appt_date.weekday() == 6:
                continue
            n_today = RNG.randint(4, 9) if day_offset <= 3 else RNG.randint(2, 7)
            for slot in range(n_today):
                hour = 9 + slot
                if hour >= 18:
                    break
                client = RNG.choice(clients)
                dt = timezone.make_aware(datetime(appt_date.year, appt_date.month, appt_date.day,
                                                   hour, RNG.choice([0, 30])))
                status = RNG.choice(['confirmed', 'scheduled', 'scheduled'])
                a = Appointment(
                    client=client, patient=None,
                    doctor=RNG.choice(doctors),
                    starts_at=dt,
                    duration=30,
                    status=status,
                    organization=org,
                    created_by=RNG.choice(doctors),
                    notes='',
                )
                appointments.append(a)

        Appointment.objects.bulk_create(appointments, ignore_conflicts=False)
        self.stdout.write(f'  Appointments: {len(appointments)}')
        return appointments

    # ─────────────────────────────────────────────────────────────────
    # VISITS (клінічний журнал)
    # ─────────────────────────────────────────────────────────────────

    def _seed_visits(self, patients, doctors):
        from apps.clients.models import Visit

        visits = []
        for p in RNG.sample(patients, min(80, len(patients))):
            n_visits = RNG.randint(1, 5)
            for _ in range(n_visits):
                diag, complaint, treatment = RNG.choice(DIAGNOSES_TREATMENT)
                days_ago = RNG.randint(5, 180)
                dt = timezone.now() - timedelta(days=days_ago)
                visits.append(Visit(
                    patient=p,
                    doctor=RNG.choice(doctors),
                    date=dt,
                    complaint=complaint,
                    diagnosis=diag,
                    treatment=treatment,
                    notes='',
                ))

        Visit.objects.bulk_create(visits)
        self.stdout.write(f'  Visits: {len(visits)}')

    # ─────────────────────────────────────────────────────────────────
    # INVOICES  (головний блок — виторг)
    # ─────────────────────────────────────────────────────────────────

    def _seed_invoices(self, org, clients, patients, doctors, services):
        from apps.billing.models import Invoice, InvoiceLine
        from apps.inventory.models import Product

        # Базовий тренд: лютий–липень 2026 + поточний місяць
        month_config = [
            (SIX_MONTHS_AGO.year, SIX_MONTHS_AGO.month, 35),
            (None, None, 38),  # +1 місяць
            (None, None, 42),
            (None, None, 46),
            (None, None, 50),
            (TODAY.year, TODAY.month, 55),  # поточний
        ]

        # Розрахуємо конкретні (year, month, count)
        months = []
        base = SIX_MONTHS_AGO.replace(day=1)
        for i, (y, m, cnt) in enumerate(month_config):
            target = base.replace(day=1)
            import calendar
            months.append((target.year, target.month, cnt))
            # Перейти до наступного місяця
            if base.month == 12:
                base = base.replace(year=base.year + 1, month=1)
            else:
                base = base.replace(month=base.month + 1)

        total_inv = 0
        svc_pool = [s for s in services]

        for year, month, count in months:
            import calendar
            days_in_month = calendar.monthrange(year, month)[1]

            for _ in range(count):
                day = RNG.randint(1, days_in_month)
                # Пропускаємо неділю
                try:
                    dt = date(year, month, day)
                except ValueError:
                    dt = date(year, month, 1)
                while dt.weekday() == 6:
                    dt += timedelta(days=1)
                    if dt.month != month:
                        dt = date(year, month, 1)

                client = RNG.choice(clients)
                patient_qs = [p for p in patients if p.client_id == client.id and not p.is_archived]
                patient = RNG.choice(patient_qs) if patient_qs else None
                doctor = RNG.choice(doctors)
                method = RNG.choices(['cash', 'card'], weights=[28, 72])[0]

                inv = Invoice.objects.create(
                    client=client,
                    patient=patient,
                    doctor=doctor,
                    status='paid',
                    payment_method=method,
                    fiscal_status=RNG.choices(['sent', 'none'], weights=[85, 15])[0],
                    discount=Decimal('0'),
                    discount_type='percent',
                    total=Decimal('0'),
                    organization=org,
                    created_by=doctor,
                    notes='',
                )

                # Backdating — головне: created_at
                dt_aware = timezone.make_aware(
                    datetime(dt.year, dt.month, dt.day,
                             RNG.randint(9, 17), RNG.choice([0, 30]))
                )
                Invoice.objects.filter(pk=inv.pk).update(
                    date=dt_aware, created_at=dt_aware
                )

                # Рядки рахунку: 1-3 послуги
                n_lines = RNG.choices([1, 2, 3], weights=[45, 40, 15])[0]
                chosen_svcs = RNG.sample(svc_pool, min(n_lines, len(svc_pool)))
                for svc in chosen_svcs:
                    qty = Decimal('1')
                    price = svc.price * Decimal(str(RNG.uniform(0.95, 1.05))).quantize(Decimal('0.01'))
                    InvoiceLine.objects.create(
                        invoice=inv,
                        line_type='service',
                        service=svc,
                        name=svc.name,
                        quantity=qty,
                        unit_price=price,
                        discount=Decimal('0'),
                        discount_type='percent',
                    )

                inv.save_total()
                total_inv += 1

        # Кілька боргових (unpaid) — для екрана "Боржники"
        for i in range(8):
            client = RNG.choice(clients[:20])
            inv = Invoice.objects.create(
                client=client,
                doctor=RNG.choice(doctors),
                status='draft',
                organization=org,
                created_by=RNG.choice(doctors),
                total=Decimal(str(RNG.choice([350, 680, 1200, 850, 2400]))),
                notes='Оплата очікується',
            )

        self.stdout.write(f'  Invoices: {total_inv} paid + 8 draft')

    # ─────────────────────────────────────────────────────────────────
    # ФІНАНСИ (витрати, каса)
    # ─────────────────────────────────────────────────────────────────

    def _seed_expenses(self, org, admin_user):
        from apps.finance.models import ExpenseCategory, Expense, CashOperation, FinanceSettings

        cats = {}
        for name in ['Оренда', 'Зарплата', 'Закупівля медикаментів', 'Комунальні послуги',
                     'Реклама та маркетинг', 'Обладнання та ремонт', 'Інше']:
            c, _ = ExpenseCategory.objects.get_or_create(name=name, organization=org)
            cats[name] = c

        expenses = []
        cash_ops = []

        for m_offset in range(6):
            exp_date = (TODAY.replace(day=1) - timedelta(days=m_offset * 30)).replace(day=1)

            # Щомісячні витрати
            monthly = [
                ('Оренда', 'cash', 15000),
                ('Комунальні послуги', 'cash', RNG.randint(3200, 4500)),
                ('Реклама та маркетинг', 'card', RNG.randint(2000, 3500)),
                ('Закупівля медикаментів', 'card', RNG.randint(5000, 9000)),
                ('Зарплата', 'cash', RNG.randint(28000, 35000)),
            ]
            for cat_name, pay_method, amt in monthly:
                e_date = exp_date + timedelta(days=RNG.randint(1, 5))
                if e_date > TODAY:
                    e_date = TODAY
                expenses.append(Expense(
                    category=cats[cat_name],
                    amount=Decimal(str(amt)),
                    date=e_date,
                    payment_method=pay_method,
                    description=f'{cat_name} — {exp_date.strftime("%B %Y")}',
                    created_by=admin_user,
                    organization=org,
                ))

            # Касова операція: вилучення для зарплати
            w_date = exp_date + timedelta(days=RNG.randint(3, 7))
            if w_date > TODAY:
                w_date = TODAY
            cash_ops.append(CashOperation(
                type='withdrawal',
                amount=Decimal(str(RNG.randint(15000, 22000))),
                date=w_date,
                description=f'Виплата зарплати — {exp_date.strftime("%B %Y")}',
                created_by=admin_user,
                organization=org,
            ))

        Expense.objects.bulk_create(expenses)
        CashOperation.objects.bulk_create(cash_ops)

        # Початковий залишок каси
        fs, _ = FinanceSettings.objects.get_or_create(
            organization=org,
            defaults={'initial_cash': Decimal('5000'), 'initial_card': Decimal('10000')},
        )

        self.stdout.write(f'  Expenses: {len(expenses)}, CashOps: {len(cash_ops)}')

    # ─────────────────────────────────────────────────────────────────
    # ЗМІНИ (для екрану зарплат)
    # ─────────────────────────────────────────────────────────────────

    def _seed_shifts(self, org, staff):
        from apps.accounts.models_payroll import Shift

        shifts = []
        for day_offset in range(90, 0, -1):
            shift_date = TODAY - timedelta(days=day_offset)
            if shift_date.weekday() == 6:
                continue
            for user in staff:
                if RNG.random() > 0.15:  # 85% відвідуваність
                    start_h = RNG.choice([9, 9, 10])
                    end_h = RNG.choice([18, 18, 19])
                    shifts.append(Shift(
                        user=user,
                        organization=org,
                        date=shift_date,
                        start_time=time(start_h, 0),
                        end_time=time(end_h, 0),
                    ))

        try:
            Shift.objects.bulk_create(shifts, ignore_conflicts=True)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  Shifts bulk_create warning: {e}'))
        self.stdout.write(f'  Shifts: до {len(shifts)} записів')

    # ─────────────────────────────────────────────────────────────────
    # ПІДСУМОК
    # ─────────────────────────────────────────────────────────────────

    def _print_summary(self, org):
        from apps.clients.models import Client, Patient
        from apps.billing.models import Invoice
        from apps.appointments.models import Appointment
        from django.db.models import Sum

        n_clients   = Client.objects.filter(organization=org).count()
        n_patients  = Patient.objects.filter(client__organization=org).count()
        n_paid      = Invoice.objects.filter(organization=org, status='paid').count()
        n_draft     = Invoice.objects.filter(organization=org, status='draft').count()
        n_appts     = Appointment.objects.filter(organization=org).count()
        revenue_sum = Invoice.objects.filter(organization=org, status='paid').aggregate(
            t=Sum('total'))['t'] or Decimal('0')

        today_appts = Appointment.objects.filter(
            organization=org,
            starts_at__date=TODAY,
            status__in=['scheduled', 'confirmed'],
        ).count()

        self.stdout.write('')
        self.stdout.write('─── Підсумок демо-тенанта ────────────────────────────')
        self.stdout.write(f'  Клієнти: {n_clients}  |  Пацієнти: {n_patients}')
        self.stdout.write(f'  Рахунки: {n_paid} paid + {n_draft} draft')
        self.stdout.write(f'  Загальний виторг: {revenue_sum:,.0f} ₴')
        self.stdout.write(f'  Записи на прийом: {n_appts} (сьогодні: {today_appts})')
        self.stdout.write(f'  Логін демо: demo / demo12345')
        self.stdout.write('──────────────────────────────────────────────────────')
