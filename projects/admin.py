from django.contrib import admin

from projects.models import Feature, Project, Task


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
    list_display = ("id", "feature", "user", "date_created", "date_updated")
    list_filter = ("feature", "user")
    search_fields = ("status",)
