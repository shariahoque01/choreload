# Seeds the fixed, global ChoreTemplate library (#10) — organized by
# room/task, not household-scoped, not editable via the UI.

from django.db import migrations

TEMPLATES = [
    ('Wash dishes', 'Kitchen', 1, 15, 10),
    ('Wipe counters', 'Kitchen', 1, 10, 5),
    ('Take out trash', 'Kitchen', 1, 5, 5),
    ('Load dishwasher', 'Kitchen', 1, 10, 10),
    ('Clean toilet', 'Bathroom', 2, 15, 15),
    ('Clean shower', 'Bathroom', 2, 20, 15),
    ('Restock towels/toiletries', 'Bathroom', 1, 5, 5),
    ('Wash a load of laundry', 'Laundry', 1, 45, 15),
    ('Fold and put away laundry', 'Laundry', 1, 20, 10),
    ('Vacuum living room', 'Living room', 2, 20, 15),
    ('Dust surfaces', 'Living room', 1, 15, 10),
    ('Make bed', 'Bedroom', 1, 5, 5),
    ('Mow the lawn', 'Yard', 3, 45, 25),
]


def seed_templates(apps, schema_editor):
    ChoreTemplate = apps.get_model('chores', 'ChoreTemplate')
    ChoreTemplate.objects.bulk_create(
        [
            ChoreTemplate(
                name=name,
                category_name=category_name,
                default_difficulty=difficulty,
                default_minutes=minutes,
                default_points=points,
            )
            for name, category_name, difficulty, minutes, points in TEMPLATES
        ]
    )


def remove_templates(apps, schema_editor):
    ChoreTemplate = apps.get_model('chores', 'ChoreTemplate')
    ChoreTemplate.objects.filter(name__in=[t[0] for t in TEMPLATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('chores', '0005_choretemplate'),
    ]

    operations = [
        migrations.RunPython(seed_templates, remove_templates),
    ]
