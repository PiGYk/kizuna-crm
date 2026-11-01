from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0024_organization_visit_labels'),
        ('inventory', '0009_perf_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='unit',
            name='hidden_for',
            field=models.ManyToManyField(
                blank=True,
                help_text='Клініки, які прибрали цю стандартну одиницю зі свого списку',
                related_name='hidden_units',
                to='clinic.organization',
                verbose_name='Прибрали зі списку',
            ),
        ),
    ]
