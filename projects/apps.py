from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    name = 'projects'

    def ready(self) -> None:
        from projects.observability import configure_dspy_mlflow

        configure_dspy_mlflow()
