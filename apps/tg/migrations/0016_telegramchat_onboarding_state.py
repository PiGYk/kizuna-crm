from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0015_telegrammessage_tgmsg_chat_tgmsgid_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramchat',
            name='onboarding_state',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Тимчасовий state-machine для реєстрації через бота: {"step": "...", "data": {...}}',
                verbose_name='Стан онбордингу',
            ),
        ),
    ]
