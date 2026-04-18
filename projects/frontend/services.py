from __future__ import annotations

from dataclasses import dataclass, field

from projects.schemas import FeatureResponseSchema


@dataclass(slots=True)
class FeatureNode:
    feature: FeatureResponseSchema
    children: list["FeatureNode"] = field(default_factory=list)


@dataclass(slots=True)
class FeatureOption:
    id: int
    label: str


def features_for_project(
    *,
    project_id: int,
    features: list[FeatureResponseSchema],
) -> list[FeatureResponseSchema]:
    return [feature for feature in features if feature.project_id == project_id]


def build_feature_tree(features: list[FeatureResponseSchema]) -> list[FeatureNode]:
    nodes_by_id = {feature.id: FeatureNode(feature=feature) for feature in features}
    roots: list[FeatureNode] = []

    for feature in features:
        node = nodes_by_id[feature.id]
        parent_id = feature.parent_feature_id
        if parent_id is None:
            roots.append(node)
            continue
        parent = nodes_by_id.get(parent_id)
        if parent is None:
            roots.append(node)
            continue
        parent.children.append(node)

    sort_feature_nodes(roots)
    return roots


def sort_feature_nodes(nodes: list[FeatureNode]) -> None:
    nodes.sort(key=lambda node: (node.feature.name.lower(), node.feature.id))
    for node in nodes:
        sort_feature_nodes(node.children)


def flatten_feature_tree(nodes: list[FeatureNode]) -> list[tuple[int, FeatureResponseSchema]]:
    flattened: list[tuple[int, FeatureResponseSchema]] = []
    for node in nodes:
        flattened.append((0, node.feature))
        for depth, feature in _flatten_children(node.children, depth=1):
            flattened.append((depth, feature))
    return flattened


def build_feature_options(nodes: list[FeatureNode]) -> list[FeatureOption]:
    options: list[FeatureOption] = []
    for depth, feature in flatten_feature_tree(nodes):
        prefix = "" if depth == 0 else f"{'--' * depth} "
        options.append(FeatureOption(id=feature.id, label=f"{prefix}{feature.name}"))
    return options
def _flatten_children(
    nodes: list[FeatureNode],
    *,
    depth: int,
) -> list[tuple[int, FeatureResponseSchema]]:
    flattened: list[tuple[int, FeatureResponseSchema]] = []
    for node in nodes:
        flattened.append((depth, node.feature))
        flattened.extend(_flatten_children(node.children, depth=depth + 1))
    return flattened
