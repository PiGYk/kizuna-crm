# Написано вручну (31.10.2026): makemigrations у services тягне ще й стару
# невідображену зміну індексів — її сюди навмисно НЕ беремо.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('services', '0004_service_show_on_website'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='code',
            field=models.CharField(blank=True, db_index=True, default='', max_length=50, verbose_name='Код'),
        ),
    ]
