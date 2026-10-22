from django.db import migrations
from pgvector.django import VectorExtension


class Migration(migrations.Migration):
    """Turns on the pgvector extension in Postgres before any table uses it."""

    dependencies = []

    operations = [VectorExtension()]
