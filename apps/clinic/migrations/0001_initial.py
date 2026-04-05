from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='ClinicSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='Ветеринарна клініка', max_length=200, verbose_name='Назва клініки')),
                ('short_name', models.CharField(blank=True, default='', max_length=100, verbose_name='Коротка назва')),
                ('address', models.CharField(blank=True, default='', max_length=300, verbose_name='Адреса')),
                ('phone', models.CharField(blank=True, default='', max_length=50, verbose_name='Телефон')),
                ('email', models.EmailField(blank=True, default='', max_length=254, verbose_name='Email')),
                ('work_hours', models.CharField(blank=True, default='', max_length=100, verbose_name='Години роботи')),
                ('website', models.CharField(blank=True, default='', max_length=200, verbose_name='Веб-сайт / домен')),
                ('currency_symbol', models.CharField(default='₴', max_length=5, verbose_name='Символ валюти')),
                ('bot_base_url', models.CharField(blank=True, default='', help_text='Використовується для генерації PDF у Telegram боті. Наприклад: https://crm.example.com', max_length=200, verbose_name='Base URL для бота (PDF)')),
            ],
            options={
                'verbose_name': 'Налаштування клініки',
            },
        ),
    ]
