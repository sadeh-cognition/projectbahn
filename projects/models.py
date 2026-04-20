from __future__ import annotations

import base64
import hashlib

from django.contrib.auth.hashers import make_password
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _build_fernet() -> Fernet:
    secret = settings.SECRET_KEY.encode("utf-8")
    digest = hashlib.sha256(secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


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
    encrypted_api_key = models.TextField(blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def set_api_key(self, api_key: str) -> None:
        self.api_key_hash = make_password(api_key)
        self.encrypted_api_key = _build_fernet().encrypt(api_key.encode("utf-8")).decode("utf-8")

    def get_api_key(self) -> str:
        if not self.encrypted_api_key:
            return ""
        try:
            return _build_fernet().decrypt(self.encrypted_api_key.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return ""

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key_hash or self.encrypted_api_key)

    @property
    def api_key_usable(self) -> bool:
        return bool(self.get_api_key())

    @property
    def api_key_requires_reentry(self) -> bool:
        return self.api_key_configured and not self.api_key_usable

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


class FeatureChatThread(models.Model):
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="chat_threads")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feature_chat_threads",
    )
    title = models.CharField(max_length=255)
    chat = models.ForeignKey("django_llm_chat.Chat", on_delete=models.CASCADE, related_name="feature_threads")
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_updated", "-id"]

    def __str__(self) -> str:
        return f"{self.feature.name}: {self.title}"


class FeatureChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    thread = models.ForeignKey(FeatureChatThread, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    llm_call = models.ForeignKey(
        "django_llm_chat.LLMCall",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_messages",
    )
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date_created", "id"]

    def __str__(self) -> str:
        return f"{self.thread_id}:{self.role}"
