import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0024_hospitalization_outcome'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LabResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('panel', models.CharField(choices=[('biochemistry', 'Біохімія крові'), ('hematology', 'Загальний аналіз крові'), ('cytology', 'Цитологія'), ('histology', 'Гістологія'), ('other', 'Інший аналіз')], max_length=20, verbose_name='Бланк')),
                ('title', models.CharField(blank=True, help_text='Порожньо — назва бланку', max_length=120, verbose_name='Назва')),
                ('date', models.DateField(default=django.utils.timezone.localdate, verbose_name='Дата')),
                ('material', models.CharField(blank=True, max_length=200, verbose_name='Матеріал')),
                ('rows', models.JSONField(blank=True, default=list, verbose_name='Показники')),
                ('description', models.TextField(blank=True, verbose_name='Опис')),
                ('conclusion', models.TextField(blank=True, verbose_name='Висновок')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Створив')),
                ('doctor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='lab_results', to=settings.AUTH_USER_MODEL, verbose_name='Лікар')),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lab_results', to='clients.patient', verbose_name='Пацієнт')),
            ],
            options={
                'verbose_name': 'Бланк аналізу',
                'verbose_name_plural': 'Бланки аналізів',
                'ordering': ('-date', '-pk'),
            },
        ),
    ]
