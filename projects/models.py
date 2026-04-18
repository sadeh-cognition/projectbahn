from __future__ import annotations

from django.conf import settings
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class Feature(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="features")
    parent_feature = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_features",
    )
    name = models.CharField(max_length=255)
    description = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class Task(models.Model):
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="tasks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tasks")
    status = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Task {self.id} for feature {self.feature_id}"
