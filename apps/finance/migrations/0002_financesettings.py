from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='FinanceSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('initial_cash', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Початковий залишок готівки')),
                ('initial_card', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Початковий залишок картки')),
            ],
            options={
                'verbose_name': 'Налаштування балансу',
            },
        ),
    ]
