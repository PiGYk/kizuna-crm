"""Бланк «Загальний аналіз сечі» і поля шапки бланку (ANVAR 08.11.2026). Новий варіант вибору й нове поле —
наявні бланки без змін."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0027_ultrasound_kidneys_other'),
    ]

    operations = [
        migrations.AlterField(
            model_name='labresult',
            name='panel',
            field=models.CharField(choices=[('biochemistry', 'Біохімія крові'), ('hematology', 'Загальний аналіз крові'),
                                            ('urinalysis', 'Загальний аналіз сечі'), ('cytology', 'Цитологія'),
                                            ('histology', 'Гістологія'), ('other', 'Інший аналіз')],
                                   max_length=20, verbose_name='Бланк'),
        ),
        migrations.AddField(
            model_name='labresult',
            name='extra',
            field=models.JSONField(blank=True, default=dict, verbose_name='Додатково'),
        ),
    ]
