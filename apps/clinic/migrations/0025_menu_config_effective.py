"""Зафіксувати в налаштуваннях доступу те, що реально діяло до 01.11.2026.

Чотири галочки з восьми нічого не робили: «Рахунки (всі)» (лікар завжди бачив лише свої
рахунки, асистент — усі), «Боржники» й «Доходність» (показувались разом з «Аналітикою»),
«Розсилки» (відкривались лише адміністратору). Тепер вони діють — тож у клініках зі
збереженими налаштуваннями ставимо їм значення, як було насправді, щоб ні в кого нічого
раптово не зникло й не з'явилось. Клініки без збережених налаштувань беруть типові
значення, а вони вже збігаються з тим, як було.
"""
from django.db import migrations

EFFECTIVE_BILLING = {'doctor': False, 'assistant': True}


def forwards(apps, schema_editor):
    Organization = apps.get_model('clinic', 'Organization')
    for org in Organization.objects.exclude(role_menu_config={}).exclude(role_menu_config__isnull=True):
        cfg = org.role_menu_config
        if not isinstance(cfg, dict):
            continue
        changed = False
        for role, items in cfg.items():
            if role not in EFFECTIVE_BILLING or not isinstance(items, dict):
                continue
            analytics = bool(items.get('analytics', False))
            want = {
                'billing': EFFECTIVE_BILLING[role],
                'debtors': analytics,
                'revenue': analytics,
                'broadcast': False,
            }
            for key, value in want.items():
                if items.get(key) != value:
                    items[key] = value
                    changed = True
        if changed:
            org.role_menu_config = cfg
            org.save(update_fields=['role_menu_config'])


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0024_organization_visit_labels'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
