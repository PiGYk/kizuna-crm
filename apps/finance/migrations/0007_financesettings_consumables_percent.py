from decimal import Decimal

from django.db import migrations, models


def kizuna_5(apps, schema_editor):
    """Kizuna (org 1) і далі віднімає 5% (давнє правило клініки); решта клінік — 0, вмикають самі."""
    FS = apps.get_model('finance', 'FinanceSettings')
    Org = apps.get_model('clinic', 'Organization')
    if Org.objects.filter(pk=1).exists():
        FS.objects.update_or_create(organization_id=1, defaults={'consumables_percent': Decimal('5')})


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0006_perf_indexes'),
        ('clinic', '0027_page_background_lab_templates'),
    ]

    operations = [
        migrations.AddField(
            model_name='financesettings',
            name='consumables_percent',
            field=models.DecimalField(decimal_places=1, default=0, max_digits=4, verbose_name='Розхідники, % від виручки послуг без складу'),
        ),
        migrations.RunPython(kizuna_5, migrations.RunPython.noop),
    ]
