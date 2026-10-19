from django.db import models


class Language(models.TextChoices):
    UZ = "uz", "O'zbekcha"
    RU = "ru", "Русский"
    EN = "en", "English"


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
