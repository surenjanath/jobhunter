from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_interview_session'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='llm',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
