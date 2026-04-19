from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import field_validator


def _coerce_optional_int(value: object) -> object:
    if value == "":
        return None
    return value


class ProjectCreateSchema(Schema):
    name: str
    description: str


class ProjectUpdateSchema(Schema):
    name: str
    description: str


class ProjectResponseSchema(Schema):
    id: int
    entity_type: str
    name: str
    description: str
    date_created: datetime
    date_updated: datetime


class FeatureCreateSchema(Schema):
    project_id: int
    parent_feature_id: int | None = None
    name: str
    description: str

    @field_validator("parent_feature_id", mode="before")
    @classmethod
    def empty_parent_feature_id_is_none(cls, value: object) -> object:
        return _coerce_optional_int(value)


class FeatureUpdateSchema(Schema):
    project_id: int
    parent_feature_id: int | None = None
    name: str
    description: str

    @field_validator("parent_feature_id", mode="before")
    @classmethod
    def empty_parent_feature_id_is_none(cls, value: object) -> object:
        return _coerce_optional_int(value)


class FeatureResponseSchema(Schema):
    id: int
    entity_type: str
    project_id: int
    parent_feature_id: int | None
    name: str
    description: str
    date_created: datetime
    date_updated: datetime


class TaskCreateSchema(Schema):
    feature_id: int
    user_id: int
    title: str
    description: str = ""
    status: str


class TaskUpdateSchema(Schema):
    feature_id: int
    user_id: int
    title: str
    description: str = ""
    status: str


class TaskResponseSchema(Schema):
    id: int
    entity_type: str
    project_id: int
    project_name: str
    feature_id: int
    feature_name: str
    user_id: int
    user_username: str
    title: str
    description: str
    status: str
    date_created: datetime
    date_updated: datetime


class EventLogResponseSchema(Schema):
    id: int
    entity_type: str
    entity_id: int
    event_type: str
    event_details: dict[str, object]


class EventLogPageResponseSchema(Schema):
    items: list[EventLogResponseSchema]
    total: int
    page: int
    page_size: int


class UserResponseSchema(Schema):
    id: int
    username: str
