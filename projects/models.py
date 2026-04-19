from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.conf import settings
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class ProjectLLMConfig(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="llm_config")
    provider = models.CharField(max_length=255, blank=True)
    llm_name = models.CharField(max_length=255, blank=True)
    api_key_hash = models.CharField(max_length=255, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def set_api_key(self, api_key: str) -> None:
        self.api_key_hash = make_password(api_key)

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key_hash)

    def __str__(self) -> str:
        return f"LLM config for {self.project}"


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
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title


class EventLog(models.Model):
    class EntityType(models.TextChoices):
        PROJECT = "Project", "Project"
        FEATURE = "Feature", "Feature"
        TASK = "Task", "Task"

    class EventType(models.TextChoices):
        CREATED = "created", "created"
        MODIFIED = "modified", "modified"
        DELETED = "deleted", "deleted"

    entity_type = models.CharField(max_length=32, choices=EntityType.choices)
    entity_id = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    event_details = models.JSONField(default=dict)

    def __str__(self) -> str:
        return f"{self.entity_type}:{self.entity_id}:{self.event_type}"
