from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from projects.api import api
from projects import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("projects/", views.project_list, name="project-list"),
    path("workspace/", views.workspace, name="workspace"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
