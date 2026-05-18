from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0008_broadcast'),
    ]

    operations = [
        migrations.AddField(
            model_name='broadcast',
            name='cooldown_days',
            field=models.PositiveSmallIntegerField(
                default=0,
                verbose_name='Не надсилати тим, хто отримував розсилку (днів)',
                help_text='0 — без обмежень',
            ),
        ),
        migrations.CreateModel(
            name='BroadcastRecipient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[('sent', 'Відправлено'), ('failed', 'Помилка'), ('skipped', 'Пропущено')],
                    default='sent',
                    max_length=10,
                    verbose_name='Статус',
                )),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('broadcast', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='recipients',
                    to='tg.broadcast',
                    verbose_name='Розсилка',
                )),
                ('chat', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='broadcast_receipts',
                    to='tg.telegramchat',
                    verbose_name='Чат',
                )),
            ],
            options={
                'verbose_name': 'Отримувач розсилки',
                'verbose_name_plural': 'Отримувачі розсилки',
                'ordering': ['-sent_at'],
                'unique_together': {('broadcast', 'chat')},
            },
        ),
    ]
