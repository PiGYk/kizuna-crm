from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0026_visit_exam'),
    ]

    operations = [
        migrations.AddField(model_name='ultrasoundreport', name='kidney_left_echogenicity',
                            field=models.CharField(blank=True, max_length=50, verbose_name='Ехогенність лівої')),
        migrations.AddField(model_name='ultrasoundreport', name='kidney_left_pelvis',
                            field=models.CharField(blank=True, help_text='Не розширена / розширена до ___ мм', max_length=100, verbose_name='Ниркова миска лівої')),
        migrations.AddField(model_name='ultrasoundreport', name='kidney_right_echogenicity',
                            field=models.CharField(blank=True, max_length=50, verbose_name='Ехогенність правої')),
        migrations.AddField(model_name='ultrasoundreport', name='kidney_right_pelvis',
                            field=models.CharField(blank=True, help_text='Не розширена / розширена до ___ мм', max_length=100, verbose_name='Ниркова миска правої')),
        migrations.AlterField(model_name='ultrasoundreport', name='kidney_echogenicity',
                              field=models.CharField(blank=True, max_length=50, verbose_name='Ехогенність нирок (обидві, давнє)')),
        migrations.AlterField(model_name='ultrasoundreport', name='kidney_pelvis',
                              field=models.CharField(blank=True, help_text='Не розширена / розширена до ___ мм', max_length=100, verbose_name='Ниркова миска (обидві, давнє)')),
        migrations.AddField(model_name='ultrasoundreport', name='other_notes',
                            field=models.TextField(blank=True, verbose_name='Інше')),
    ]
