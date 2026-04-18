from __future__ import annotations

from datetime import UTC, datetime

from projects.frontend.services import build_feature_tree, features_for_project, flatten_feature_tree
from projects.schemas import FeatureResponseSchema


def make_feature(
    *,
    feature_id: int,
    project_id: int,
    parent_feature_id: int | None,
    name: str,
) -> FeatureResponseSchema:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return FeatureResponseSchema(
        id=feature_id,
        project_id=project_id,
        parent_feature_id=parent_feature_id,
        name=name,
        description=f"{name} description",
        date_created=timestamp,
        date_updated=timestamp,
    )


def test_features_for_project_filters_to_single_project() -> None:
    features = [
        make_feature(feature_id=1, project_id=10, parent_feature_id=None, name="Auth"),
        make_feature(feature_id=2, project_id=11, parent_feature_id=None, name="Billing"),
    ]

    result = features_for_project(project_id=10, features=features)

    assert [feature.id for feature in result] == [1]


def test_build_feature_tree_and_flatten_preserve_hierarchy() -> None:
    features = [
        make_feature(feature_id=3, project_id=10, parent_feature_id=2, name="Role Rules"),
        make_feature(feature_id=1, project_id=10, parent_feature_id=None, name="Auth"),
        make_feature(feature_id=2, project_id=10, parent_feature_id=1, name="Permissions"),
    ]

    flattened = flatten_feature_tree(build_feature_tree(features))

    assert [(depth, feature.id) for depth, feature in flattened] == [(0, 1), (1, 2), (2, 3)]
