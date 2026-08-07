from django.db import migrations, models
import apps.clinic.uploads


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0018_client_archived_at_client_is_archived_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='patientanalysis',
            name='image',
            field=models.FileField(upload_to=apps.clinic.uploads.analysis_image_path, verbose_name='Файл'),
        ),
    ]
