from django.db import migrations, models
import django.db.models.deletion


def assign_existing_to_first_org(apps, schema_editor):
    """Прив'язуємо існуючий singleton-запис до першої організації."""
    FinanceSettings = apps.get_model('finance', 'FinanceSettings')
    Organization = apps.get_model('clinic', 'Organization')
    first_org = Organization.objects.order_by('pk').first()
    if first_org:
        FinanceSettings.objects.filter(organization__isnull=True).update(organization=first_org)


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0002_org_fk'),
        ('finance', '0003_org_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='financesettings',
            name='organization',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='finance_settings',
                to='clinic.organization',
                verbose_name='Організація',
            ),
        ),
        migrations.RunPython(assign_existing_to_first_org, migrations.RunPython.noop),
    ]
