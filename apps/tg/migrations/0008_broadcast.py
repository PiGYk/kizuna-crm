from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0007_alter_telegrammessage_media_file'),
        ('clinic', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Broadcast',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField(verbose_name='Текст повідомлення')),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Чернетка'),
                        ('sending', 'Відправляється'),
                        ('done', 'Завершено'),
                    ],
                    default='draft',
                    max_length=10,
                    verbose_name='Статус',
                )),
                ('total', models.PositiveIntegerField(default=0, verbose_name='Всього')),
                ('sent', models.PositiveIntegerField(default=0, verbose_name='Відправлено')),
                ('failed', models.PositiveIntegerField(default=0, verbose_name='Помилок')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='broadcasts',
                    to='clinic.organization',
                    verbose_name='Організація',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Автор',
                )),
            ],
            options={
                'verbose_name': 'Розсилка',
                'verbose_name_plural': 'Розсилки',
                'ordering': ['-created_at'],
            },
        ),
    ]
