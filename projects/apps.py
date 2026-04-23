from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    name = 'projects'

    def ready(self) -> None:
        from projects.observability import configure_dspy_mlflow
        from projects.lmstudio import ensure_lmstudio_embedding_model_loaded

        configure_dspy_mlflow()
        ensure_lmstudio_embedding_model_loaded()
