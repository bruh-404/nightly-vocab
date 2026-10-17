"""Data migration: Ensure existing users have UserControl and AiUsage has default source."""
from django.db import migrations


def forward_func(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserControl = apps.get_model("services", "UserControl")
    AiUsage = apps.get_model("services", "AiUsage")

    # Create UserControl for any users that don't have one
    for u in User.objects.all():
        UserControl.objects.get_or_create(user=u)

    # Ensure source is 'shared' for any null or empty rows
    AiUsage.objects.filter(source="").update(source="shared")


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("services", "0002_siteconfig_adminauditlog_usercontrol_telegramusage_and_more"),
    ]

    operations = [
        migrations.RunPython(forward_func, reverse_func),
    ]
