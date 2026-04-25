from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from typing import Any, Iterable


def _build_fernet() -> Fernet:
    secret = settings.LLM_API_KEY_ENCRYPTION_KEY.encode("utf-8")
    digest = hashlib.sha256(secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name

    @classmethod
    def get_all_ordered(cls) -> QuerySet[Project]:
        return cls.objects.order_by("id")

    @classmethod
    def get_all_ids_ordered_by_date(cls) -> QuerySet[Project]:
        return cls.objects.order_by("date_created", "id").values_list("id", flat=True)

    @classmethod
    def get_total_count(cls) -> int:
        return cls.objects.count()

    @classmethod
    def get_by_id_or_404(cls, project_id: int) -> Project:
        return get_object_or_404(cls, id=project_id)

    @classmethod
    def create_project(cls, *, name: str, description: str) -> Project:
        return cls.objects.create(name=name, description=description)

    def get_project_llm_config(self) -> ProjectLLMConfig:
        from projects.feature_chat import FeatureChatConfigurationError

        try:
            config = self.llm_config
        except ObjectDoesNotExist as exc:
            raise FeatureChatConfigurationError(
                "Configure the project LLM before starting a feature chat."
            ) from exc

        if not config.provider or not config.llm_name:
            raise FeatureChatConfigurationError("Project LLM config is incomplete.")
        if config.api_key_requires_reentry:
            raise FeatureChatConfigurationError(
                "This project has a legacy API key entry. Re-save the API key in project settings before chatting."
            )
        if not config.api_key_usable:
            raise FeatureChatConfigurationError("Project LLM API key is missing.")
        return config


class ProjectLLMConfig(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="llm_config")
    provider = models.CharField(max_length=255, blank=True)
    llm_name = models.CharField(max_length=255, blank=True)
    api_key_hash = models.CharField(max_length=255, blank=True)
    encrypted_api_key = models.TextField(blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    @classmethod
    def get_or_create_for_project(cls, project: Project) -> tuple[ProjectLLMConfig, bool]:
        return cls.objects.get_or_create(project=project)

    @classmethod
    def get_for_project(cls, project: Project) -> ProjectLLMConfig | None:
        return cls.objects.filter(project=project).first()

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


class ProjectCodebaseAgentConfig(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="codebase_agent_config")
    url = models.URLField(blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    @classmethod
    def get_or_create_for_project(
        cls, project: Project
    ) -> tuple[ProjectCodebaseAgentConfig, bool]:
        return cls.objects.get_or_create(project=project)

    @classmethod
    def get_for_project(cls, project: Project) -> ProjectCodebaseAgentConfig | None:
        return cls.objects.filter(project=project).first()

    def __str__(self) -> str:
        return f"Codebase agent config for {self.project}"


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

    @classmethod
    def get_all_with_relations_ordered(cls) -> QuerySet[Feature]:
        return cls.objects.select_related("project", "parent_feature").order_by("id")

    @classmethod
    def get_by_id_with_relations_or_404(cls, feature_id: int) -> Feature:
        return get_object_or_404(cls.objects.select_related("project", "parent_feature"), id=feature_id)

    @classmethod
    def get_by_id_or_404(cls, feature_id: int) -> Feature:
        return get_object_or_404(cls, id=feature_id)

    @classmethod
    def get_by_id_with_project_or_404(cls, feature_id: int) -> Feature:
        return get_object_or_404(cls.objects.select_related("project"), id=feature_id)

    @classmethod
    def get_features_for_project_with_relations(cls, project_id: int) -> QuerySet[Feature]:
        return cls.objects.select_related("project", "parent_feature").filter(project_id=project_id)

    @classmethod
    def get_ids_for_project(cls, project_id: int) -> QuerySet[Feature]:
        return cls.objects.filter(project_id=project_id).order_by("id").values_list("id", flat=True)

    @classmethod
    def get_ids_for_parent_feature(cls, parent_feature_id: int) -> QuerySet[Feature]:
        return cls.objects.filter(parent_feature_id=parent_feature_id).order_by("id").values_list("id", flat=True)

    @classmethod
    def get_all_ids_ordered_by_date(cls) -> QuerySet[Feature]:
        return cls.objects.order_by("date_created", "id").values_list("id", flat=True)

    @classmethod
    def get_total_count(cls) -> int:
        return cls.objects.count()

    @classmethod
    def create_feature(cls, *, project: Project, parent_feature: Feature | None, name: str, description: str) -> Feature:
        return cls.objects.create(
            project=project,
            parent_feature=parent_feature,
            name=name,
            description=description,
        )


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

    @classmethod
    def get_base_queryset_with_relations(cls) -> QuerySet[Task]:
        return cls.objects.select_related("feature__project", "user")

    @classmethod
    def get_by_id_or_404(cls, task_id: int) -> Task:
        return get_object_or_404(cls, id=task_id)

    @classmethod
    def get_by_id_with_relations_or_404(cls, task_id: int) -> Task:
        return get_object_or_404(cls.get_base_queryset_with_relations(), id=task_id)

    @classmethod
    def get_ids_for_project(cls, project_id: int) -> QuerySet[Task]:
        return cls.objects.filter(feature__project_id=project_id).order_by("id").values_list("id", flat=True)

    @classmethod
    def get_ids_for_feature(cls, feature_id: int) -> QuerySet[Task]:
        return cls.objects.filter(feature_id=feature_id).order_by("id").values_list("id", flat=True)

    @classmethod
    def get_all_ids_ordered_by_date(cls) -> QuerySet[Task]:
        return cls.objects.order_by("date_created", "id").values_list("id", flat=True)

    @classmethod
    def get_total_count(cls) -> int:
        return cls.objects.count()

    @classmethod
    def create_task(cls, *, feature: Feature, user: Any, title: str, description: str, status: str) -> Task:
        return cls.objects.create(
            feature=feature,
            user=user,
            title=title,
            description=description,
            status=status,
        )


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

    @classmethod
    def get_base_queryset_ordered(cls) -> QuerySet[EventLog]:
        return cls.objects.order_by("-id")

    @classmethod
    def get_keys_for_event_type(cls, event_type: str) -> QuerySet[EventLog]:
        return cls.objects.filter(event_type=event_type).values_list("entity_type", "entity_id")

    @classmethod
    def create_log(cls, *, entity_type: str, entity_id: int, event_type: str, event_details: dict[str, Any]) -> EventLog:
        return cls.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            event_details=event_details,
        )

    @classmethod
    def bulk_create_logs(cls, logs: Iterable[EventLog]) -> None:
        cls.objects.bulk_create(logs)


class FeatureChatThread(models.Model):
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="chat_threads")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feature_chat_threads",
    )
    title = models.CharField(max_length=255)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_updated", "-id"]

    def __str__(self) -> str:
        return f"{self.feature.name}: {self.title}"

    @classmethod
    def get_threads_for_feature_and_owner(cls, *, feature_id: int, owner_id: int) -> QuerySet[FeatureChatThread]:
        return cls.objects.select_related("owner").filter(feature_id=feature_id, owner_id=owner_id)

    @classmethod
    def get_by_id_and_owner_or_404(cls, *, thread_id: int, feature_id: int, owner_id: int) -> FeatureChatThread:
        return get_object_or_404(
            cls.objects.select_related("feature__project", "owner"),
            id=thread_id,
            feature_id=feature_id,
            owner_id=owner_id,
        )

    @classmethod
    def create_thread(cls, *, feature: Feature, owner: Any, title: str) -> FeatureChatThread:
        return cls.objects.create(
            feature=feature,
            owner=owner,
            title=title,
        )

    def list_thread_messages(self) -> list[FeatureChatMessage]:
        return list(self.messages.order_by("date_created", "id"))

    def create_feature_chat_assistant_message(
        self,
        *,
        config: ProjectLLMConfig,
        assistant_text: str,
    ) -> FeatureChatMessage:
        llm_name = config.llm_name if "/" in config.llm_name else f"{config.provider}/{config.llm_name}"
        assistant_message = self.messages.create(
            role=FeatureChatMessage.Role.ASSISTANT,
            text=assistant_text.strip(),
            metadata={
                "provider": config.provider,
                "llm_name": llm_name,
            },
        )
        self.save(update_fields=["date_updated"])
        return assistant_message


class FeatureChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    thread = models.ForeignKey(FeatureChatThread, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    llm_call_id = models.PositiveBigIntegerField(null=True, blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date_created", "id"]

    def __str__(self) -> str:
        return f"{self.thread_id}:{self.role}"

    @classmethod
    def create_message(cls, *, thread: FeatureChatThread, role: str, text: str, metadata: dict[str, Any] | None = None) -> FeatureChatMessage:
        return cls.objects.create(
            thread=thread,
            role=role,
            text=text,
            metadata=metadata or {},
        )
