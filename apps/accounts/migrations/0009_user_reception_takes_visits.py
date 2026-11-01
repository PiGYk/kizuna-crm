from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_user_shift_color'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('admin', 'Адміністратор'), ('doctor', 'Лікар'), ('assistant', 'Асистент'),
                         ('reception', 'Адміністратор рецепції')],
                default='doctor', max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='takes_visits',
            field=models.BooleanField(
                default=True, verbose_name='Веде прийоми',
                help_text='Показувати серед лікарів і виконавців у прийомах, розкладі й стаціонарі',
            ),
        ),
    ]
