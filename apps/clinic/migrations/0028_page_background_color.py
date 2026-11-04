"""Свій колір фону сторінок (ANVAR 04.11.2026). Новий варіант вибору й нове поле — наявні клініки без змін."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0027_page_background_lab_templates'),
    ]

    operations = [
        migrations.AlterField(
            model_name='organization',
            name='page_background',
            field=models.CharField(choices=[('light', 'Світлий'), ('gray', 'Сірий — мʼякший для очей'), ('custom', 'Свій колір')], default='light', max_length=10, verbose_name='Фон сторінок'),
        ),
        migrations.AddField(
            model_name='organization',
            name='page_background_color',
            field=models.CharField(blank=True, default='', max_length=7, verbose_name='Свій колір фону'),
        ),
    ]
