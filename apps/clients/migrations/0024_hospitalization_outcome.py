import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0023_ultrasoundreport_pancreas_echogenicity_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='hospitalization',
            name='admitted_at',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Дата надходження'),
        ),
        migrations.AddField(
            model_name='hospitalization',
            name='outcome',
            field=models.CharField(
                blank=True, max_length=20, verbose_name='Результат',
                choices=[
                    ('recovered', 'Одужав'), ('improved', 'Покращення'), ('no_change', 'Без змін'),
                    ('refused', 'Відмова від подальшого лікування'),
                    ('transferred', 'Переведено в іншу клініку'),
                    ('euthanasia', 'Евтаназія'), ('died', 'Помер'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='hospitalization',
            name='discharge_condition',
            field=models.CharField(blank=True, max_length=200, verbose_name='Стан на момент виписки'),
        ),
    ]
