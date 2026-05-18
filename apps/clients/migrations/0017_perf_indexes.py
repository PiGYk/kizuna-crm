from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0016_extend_species'),
    ]

    operations = [
        # Vaccine — reminder/expiry scans by org
        migrations.AddIndex(
            model_name='vaccine',
            index=models.Index(fields=['patient'], name='vacc_patient_idx'),
        ),
        migrations.AddIndex(
            model_name='vaccine',
            index=models.Index(fields=['next_date'], name='vacc_next_date_idx'),
        ),
        migrations.AddIndex(
            model_name='vaccine',
            index=models.Index(fields=['valid_until'], name='vacc_valid_until_idx'),
        ),
        # Visit — history + reports
        migrations.AddIndex(
            model_name='visit',
            index=models.Index(fields=['patient', '-date'], name='visit_patient_date_idx'),
        ),
        migrations.AddIndex(
            model_name='visit',
            index=models.Index(fields=['date'], name='visit_date_idx'),
        ),
        # Patient — listings & filters
        migrations.AddIndex(
            model_name='patient',
            index=models.Index(fields=['client', 'name'], name='patient_client_name_idx'),
        ),
        migrations.AddIndex(
            model_name='patient',
            index=models.Index(fields=['species'], name='patient_species_idx'),
        ),
        # Hospitalization — active stationary filter
        migrations.AddIndex(
            model_name='hospitalization',
            index=models.Index(fields=['organization', 'status'], name='hosp_org_status_idx'),
        ),
    ]
