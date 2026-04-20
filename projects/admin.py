from django.contrib import admin

from projects.models import (
    EventLog,
    Feature,
    Project,
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
