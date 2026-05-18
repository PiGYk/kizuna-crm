from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0013_quickreplyprompt'),
    ]

    operations = [
        # TelegramMessage — chat history pagination
        migrations.AddIndex(
            model_name='telegrammessage',
            index=models.Index(
                fields=['chat', '-id'],
                name='tgmsg_chat_id_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='telegrammessage',
            index=models.Index(
                fields=['chat', 'direction', 'is_read'],
                name='tgmsg_chat_dir_read_idx',
            ),
        ),
        # TelegramChat — inbox sort
        migrations.AddIndex(
            model_name='telegramchat',
            index=models.Index(
                fields=['organization', '-last_message_at'],
                name='tgchat_org_last_idx',
            ),
        ),
    ]
