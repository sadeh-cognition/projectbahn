from django.contrib import admin

from projects.models import (
    EventLog,
    Feature,
    FeatureChatMessage,
    FeatureChatThread,
    Project,
    ProjectLLMConfig,
    Task,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "date_created", "date_updated")
    search_fields = ("name",)


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "project", "parent_feature", "date_created", "date_updated")
    list_filter = ("project",)
    search_fields = ("name", "description")


@admin.register(ProjectLLMConfig)
class ProjectLLMConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "provider",
        "llm_name",
        "api_key_configured",
        "api_key_usable",
        "date_created",
        "date_updated",
    )
    search_fields = ("project__name", "provider", "llm_name")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "feature", "user", "status", "date_created", "date_updated")
    list_filter = ("feature", "user", "status")
    search_fields = ("title", "description", "status")


@admin.register(EventLog)
class EventLogAdmin(admin.ModelAdmin):
    list_display = ("id", "entity_type", "entity_id", "event_type")
    list_filter = ("entity_type", "event_type")
    search_fields = ("entity_type", "event_type")


@admin.register(FeatureChatThread)
class FeatureChatThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "feature", "owner", "date_created", "date_updated")
    list_filter = ("feature__project", "owner")
    search_fields = ("title", "feature__name", "owner__username")


@admin.register(FeatureChatMessage)
class FeatureChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "role", "llm_call_id", "date_created")
    list_filter = ("role",)
    search_fields = ("thread__title", "thread__feature__name", "text")
