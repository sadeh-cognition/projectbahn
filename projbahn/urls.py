from django.contrib import admin
from django.urls import path
from projects.api import api
from projects import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("workspace/", views.workspace, name="workspace"),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
