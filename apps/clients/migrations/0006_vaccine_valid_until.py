from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0005_weightrecord'),
    ]

    operations = [
        migrations.AddField(
            model_name='vaccine',
            name='valid_until',
            field=models.DateField(blank=True, null=True, verbose_name='Діє до'),
        ),
    ]
