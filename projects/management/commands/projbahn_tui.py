from __future__ import annotations

from typing import Callable, NoReturn, TypeVar

import djclick as click
from ninja.errors import HttpError
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from projects.frontend.services import build_feature_tree, features_for_project, flatten_feature_tree
from projects.schemas import (
    FeatureCreateSchema,
    FeatureResponseSchema,
    FeatureUpdateSchema,
    ProjectCreateSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
)
from projects.tui.api_client import ApiClient

console = Console()
ResultT = TypeVar("ResultT")


@click.command()
@click.option("--api-base-url", default="http://127.0.0.1:8001/api", show_default=True)
def command(api_base_url: str) -> None:
    """Run the terminal UI for projects and nested features."""
    app = ProjbahnTui(api_client=ApiClient(base_url=api_base_url))
    app.run()


class ProjbahnTui:
    def __init__(self, *, api_client: ApiClient) -> None:
        self.api_client = api_client

    def run(self) -> None:
        console.print(
            Panel.fit(
                "Project manager for projects and nested features.\n"
                "Run `uv run manage.py runserver 8001` in another terminal first.",
                title="Projbahn",
            ),
        )
        while True:
            self._render_projects()
            action = Prompt.ask(
                "\nProject actions",
                choices=["open", "new", "edit", "delete", "refresh", "quit"],
                default="open",
            )
            if action == "open":
                self._open_project()
                continue
            if action == "new":
                self._create_project()
                continue
            if action == "edit":
                self._edit_project()
                continue
            if action == "delete":
                self._delete_project()
                continue
            if action == "refresh":
                continue
            raise SystemExit(0)

    def _render_projects(self) -> None:
        projects = self._safe_list_projects()
        table = Table(title="Projects")
        table.add_column("ID", justify="right")
        table.add_column("Name")
        table.add_column("Description")
        table.add_column("Updated")
        for project in projects:
            table.add_row(
                str(project.id),
                project.name,
                project.description,
                project.date_updated.strftime("%Y-%m-%d %H:%M"),
            )
        if not projects:
            table.add_row("-", "No projects yet", "Create one to get started.", "-")
        console.print(table)

    def _open_project(self) -> None:
        project = self._choose_project("Open project ID")
        if project is None:
            return
        while True:
            self._render_project_detail(project)
            action = Prompt.ask(
                "\nFeature actions",
                choices=["new", "edit", "delete", "back"],
                default="new",
            )
            if action == "new":
                self._create_feature(project)
                project = self._refresh_project(project.id)
                continue
            if action == "edit":
                self._edit_feature(project)
                project = self._refresh_project(project.id)
                continue
            if action == "delete":
                self._delete_feature(project)
                project = self._refresh_project(project.id)
                continue
            return

    def _render_project_detail(self, project: ProjectResponseSchema) -> None:
        features = features_for_project(project_id=project.id, features=self._safe_list_features())
        table = Table(title=f"Project #{project.id}: {project.name}")
        table.add_column("Description")
        table.add_row(project.description or "-")
        console.print(table)

        feature_table = Table(title="Nested Features")
        feature_table.add_column("ID", justify="right")
        feature_table.add_column("Feature")
        feature_table.add_column("Description")
        flattened = flatten_feature_tree(build_feature_tree(features))
        for depth, feature in flattened:
            feature_table.add_row(
                str(feature.id),
                f"{'  ' * depth}{feature.name}",
                feature.description,
            )
        if not flattened:
            feature_table.add_row("-", "No features yet", "Add a parent or nested feature.")
        console.print(feature_table)

    def _create_project(self) -> None:
        payload = ProjectCreateSchema(
            name=Prompt.ask("Project name").strip(),
            description=Prompt.ask("Project description", default="").strip(),
        )
        self._run_api_call(lambda: self.api_client.create_project(payload), success_message="Project created.")

    def _edit_project(self) -> None:
        project = self._choose_project("Edit project ID")
        if project is None:
            return
        payload = ProjectUpdateSchema(
            name=Prompt.ask("Project name", default=project.name).strip(),
            description=Prompt.ask("Project description", default=project.description).strip(),
        )
        self._run_api_call(
            lambda: self.api_client.update_project(project.id, payload),
            success_message="Project updated.",
        )

    def _delete_project(self) -> None:
        project = self._choose_project("Delete project ID")
        if project is None or not Confirm.ask(f"Delete project '{project.name}'?", default=False):
            return
        self._run_api_call(
            lambda: self.api_client.delete_project(project.id),
            success_message="Project deleted.",
        )

    def _create_feature(self, project: ProjectResponseSchema) -> None:
        parent_feature = self._choose_feature(
            project=project,
            prompt_text="Parent feature ID",
            allow_blank=True,
        )
        payload = FeatureCreateSchema(
            project_id=project.id,
            parent_feature_id=None if parent_feature is None else parent_feature.id,
            name=Prompt.ask("Feature name").strip(),
            description=Prompt.ask("Feature description", default="").strip(),
        )
        self._run_api_call(lambda: self.api_client.create_feature(payload), success_message="Feature created.")

    def _edit_feature(self, project: ProjectResponseSchema) -> None:
        feature = self._choose_feature(project=project, prompt_text="Edit feature ID")
        if feature is None:
            return
        parent_feature = self._choose_feature(
            project=project,
            prompt_text="New parent feature ID",
            allow_blank=True,
            excluded_feature_id=feature.id,
            default_feature_id=feature.parent_feature_id,
        )
        if feature.parent_feature_id is not None and parent_feature is None:
            chosen_label = Prompt.ask(
                "Clear the parent feature?",
                choices=["yes", "no"],
                default="no",
            )
            if chosen_label == "no":
                return
        payload = FeatureUpdateSchema(
            project_id=project.id,
            parent_feature_id=None if parent_feature is None else parent_feature.id,
            name=Prompt.ask("Feature name", default=feature.name).strip(),
            description=Prompt.ask("Feature description", default=feature.description).strip(),
        )
        self._run_api_call(
            lambda: self.api_client.update_feature(feature.id, payload),
            success_message="Feature updated.",
        )

    def _delete_feature(self, project: ProjectResponseSchema) -> None:
        feature = self._choose_feature(project=project, prompt_text="Delete feature ID")
        if feature is None or not Confirm.ask(f"Delete feature '{feature.name}'?", default=False):
            return
        self._run_api_call(
            lambda: self.api_client.delete_feature(feature.id),
            success_message="Feature deleted.",
        )

    def _choose_project(self, prompt_text: str) -> ProjectResponseSchema | None:
        projects = self._safe_list_projects()
        if not projects:
            console.print("[yellow]There are no projects yet.[/yellow]")
            return None
        return self._select_by_id(
            prompt_text=prompt_text,
            items=projects,
            item_name="project",
        )

    def _choose_feature(
        self,
        *,
        project: ProjectResponseSchema,
        prompt_text: str,
        allow_blank: bool = False,
        excluded_feature_id: int | None = None,
        default_feature_id: int | None = None,
    ) -> FeatureResponseSchema | None:
        features = [
            feature
            for feature in features_for_project(project_id=project.id, features=self._safe_list_features())
            if feature.id != excluded_feature_id
        ]
        if not features:
            if allow_blank:
                return None
            console.print("[yellow]There are no features in this project yet.[/yellow]")
            return None
        prompt_label = f"{prompt_text}{' (blank for none)' if allow_blank else ''}"
        default_label = "" if allow_blank and default_feature_id is None else str(default_feature_id or "")
        while True:
            label = Prompt.ask(prompt_label, default=default_label).strip()
            if allow_blank and label == "":
                return None
            try:
                feature_id = int(label)
            except ValueError:
                console.print("[red]Please enter a numeric ID.[/red]")
                continue
            for feature in features:
                if feature.id == feature_id:
                    return feature
            console.print("[red]No matching feature found.[/red]")

    def _refresh_project(self, project_id: int) -> ProjectResponseSchema:
        for project in self._safe_list_projects():
            if project.id == project_id:
                return project
        self._fatal(f"Project {project_id} is no longer available.")

    def _safe_list_projects(self) -> list[ProjectResponseSchema]:
        return self._run_api_call(self.api_client.list_projects, success_message=None)

    def _safe_list_features(self) -> list[FeatureResponseSchema]:
        return self._run_api_call(self.api_client.list_features, success_message=None)

    def _run_api_call(self, operation: Callable[[], ResultT], *, success_message: str | None) -> ResultT | list[object]:
        try:
            result = operation()
        except HttpError as exc:
            console.print(f"[red]API error {exc.status_code}: {exc.message}[/red]")
            return []
        except RuntimeError as exc:
            self._fatal(str(exc))
        else:
            if success_message is not None:
                console.print(f"[green]{success_message}[/green]")
            return result

    def _select_by_id(
        self,
        *,
        prompt_text: str,
        items: list[ProjectResponseSchema],
        item_name: str,
    ) -> ProjectResponseSchema | None:
        item_id = IntPrompt.ask(prompt_text)
        for item in items:
            if item.id == item_id:
                return item
        console.print(f"[red]No matching {item_name} found.[/red]")
        return None

    def _fatal(self, message: str) -> NoReturn:
        raise click.ClickException(message)
