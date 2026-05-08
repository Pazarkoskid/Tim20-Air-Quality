from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('airquality', '0002_userprofile_phone_savedlocation'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='avatar',
            field=models.CharField(blank=True, default='avatar1', max_length=20),
        ),
    ]
