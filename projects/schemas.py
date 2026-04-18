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
