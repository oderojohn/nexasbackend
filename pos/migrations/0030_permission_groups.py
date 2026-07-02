from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0029_priceschedulelog'),
    ]

    operations = [
        migrations.CreateModel(
            name='PermissionGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=100)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('permissions', models.JSONField(blank=True, default=list)),
                ('company', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='permission_groups',
                    to='pos.company',
                )),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddConstraint(
            model_name='permissiongroup',
            constraint=models.UniqueConstraint(
                fields=['company', 'name'],
                name='unique_perm_group_per_company',
            ),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='permission_groups',
            field=models.ManyToManyField(
                blank=True,
                related_name='members',
                to='pos.PermissionGroup',
            ),
        ),
    ]
