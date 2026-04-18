from __future__ import annotations

from datetime import datetime

from ninja import Schema


class ProjectCreateSchema(Schema):
    name: str
    description: str


class ProjectUpdateSchema(Schema):
    name: str
    description: str


class ProjectResponseSchema(Schema):
    id: int
    name: str
    description: str
    date_created: datetime
    date_updated: datetime


class FeatureCreateSchema(Schema):
    project_id: int
    parent_feature_id: int | None = None
    name: str
    description: str


class FeatureUpdateSchema(Schema):
    project_id: int
    parent_feature_id: int | None = None
    name: str
    description: str


class FeatureResponseSchema(Schema):
    id: int
    project_id: int
    parent_feature_id: int | None
    name: str
    description: str
    date_created: datetime
    date_updated: datetime
