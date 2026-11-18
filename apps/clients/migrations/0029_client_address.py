"""Адреса клієнта — де живе (ANVAR 18.11.2026). Нове необов'язкове поле, наявні клієнти — з порожньою адресою."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0028_labresult_urinalysis_extra'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='address',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Адреса'),
        ),
    ]
