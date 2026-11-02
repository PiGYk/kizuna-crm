from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0026_organization_lab_norms'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='page_background',
            field=models.CharField(choices=[('light', 'Світлий'), ('gray', 'Сірий — мʼякший для очей')], default='light', max_length=10, verbose_name='Фон сторінок'),
        ),
        migrations.AddField(
            model_name='organization',
            name='lab_templates',
            field=models.JSONField(blank=True, default=dict, verbose_name='Свої бланки аналізів'),
        ),
    ]
