from __future__ import annotations

from typing import TYPE_CHECKING

from ninja.errors import HttpError

if TYPE_CHECKING:
    from projects.models import Feature, Project


def validate_parent_feature(
    *,
    project: Project,
    parent_feature: Feature | None,
    feature_id: int | None = None,
) -> None:
    if parent_feature is None:
        return
    if feature_id is not None and parent_feature.id == feature_id:
        raise HttpError(400, "A feature cannot be its own parent.")
    if parent_feature.project_id != project.id:
        raise HttpError(400, "Parent feature must belong to the same project.")
    if feature_id is not None:
        ancestor = parent_feature
        while ancestor is not None:
            if ancestor.id == feature_id:
                raise HttpError(
                    400, "A feature cannot be assigned to its own descendant."
                )
            ancestor = ancestor.parent_feature
