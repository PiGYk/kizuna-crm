from django.db import migrations, models


def backfill_source(apps, schema_editor):
    """Старі записи: бот і сайт лишали мітку в нотатках, автора в них нема.

    _base_manager — бо OrgManager без org-контексту віддає порожню вибірку.
    """
    Appointment = apps.get_model('appointments', 'Appointment')
    unsigned = Appointment._base_manager.filter(created_by__isnull=True)
    unsigned.filter(notes__contains='Заявка з сайту').update(source='site')
    unsigned.filter(notes__contains='Записано через Telegram').update(source='telegram')
    unsigned.filter(notes__contains='Записано в Telegram').update(source='telegram')


class Migration(migrations.Migration):

    dependencies = [
        ('appointments', '0006_alter_appointment_duration'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='source',
            field=models.CharField(choices=[('crm', 'CRM'), ('telegram', 'Telegram'), ('site', 'Сайт')], default='crm', max_length=16, verbose_name='Звідки запис'),
        ),
        migrations.RunPython(backfill_source, migrations.RunPython.noop),
    ]
