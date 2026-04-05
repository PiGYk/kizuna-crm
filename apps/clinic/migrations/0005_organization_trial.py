from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0004_webhook_secret'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='trial_expires_at',
            field=models.DateTimeField(
                blank=True, null=True,
                verbose_name='Тріал до',
                help_text='Якщо вказано — акаунт заблокується після цієї дати.',
            ),
        ),
    ]
