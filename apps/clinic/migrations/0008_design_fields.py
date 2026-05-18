from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0007_alter_organization_trial_expires_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='logo',
            field=models.ImageField(
                blank=True, null=True,
                upload_to='org_logos/',
                verbose_name='Логотип',
                help_text='PNG або SVG, рекомендований розмір 200×60 px',
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='primary_color',
            field=models.CharField(
                default='#DEAA01', max_length=7,
                verbose_name='Акцентний колір',
                help_text='Кнопки, активні елементи. HEX, наприклад #DEAA01',
            ),
        ),
        migrations.AddField(
            model_name='organization',
            name='sidebar_color',
            field=models.CharField(
                default='#12100F', max_length=7,
                verbose_name='Колір бічної панелі',
                help_text='Фон меню. HEX, наприклад #12100F',
            ),
        ),
    ]
