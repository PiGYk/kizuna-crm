# Відповідь на конкретне повідомлення (Олег 25.11.2026). Обидва поля nullable:
# старий код, що ще крутиться до перезапуску, вставляє рядки без них — і не падає.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0017_telegramchat_autodialog_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegrammessage',
            name='reply_to',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='+', to='tg.telegrammessage',
            ),
        ),
        migrations.AddField(
            model_name='telegrammessage',
            name='reply_quote',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
