from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0009_broadcast_cooldown_broadcastrecipient'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegramchat',
            name='receive_leads',
            field=models.BooleanField(
                default=False,
                help_text='Цей чат отримуватиме повідомлення про нові заявки з сайту.',
                verbose_name='Отримувати заявки з сайту',
            ),
        ),
    ]
