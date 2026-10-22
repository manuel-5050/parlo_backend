from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model. Defined now so it can be extended later without pain."""

    email = models.EmailField("email address", unique=True)

    def __str__(self):
        return self.username
