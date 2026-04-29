import pytest
from ninja.testing import TestClient
from model_bakery import baker
from projects.api import api
from projects.models import Feature, Project
from projects.schemas import FeatureCreateSchema, FeatureUpdateSchema

@pytest.fixture
def client():
    return TestClient(api)

@pytest.mark.django_db
class TestFeatureEndpoints:
    def test_create_feature_no_parent(self, client):
        project = baker.make("projects.Project")
        payload = {
            "project_id": project.id,
            "parent_feature_id": None,
            "name": "New Feature",
            "description": "Desc"
        }
        response = client.post("/features", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Feature"
        assert Feature.objects.filter(id=data["id"]).exists()

    def test_create_feature_with_parent(self, client):
        project = baker.make("projects.Project")
        parent = baker.make("projects.Feature", project=project)
        payload = {
            "project_id": project.id,
            "parent_feature_id": parent.id,
            "name": "Sub Feature",
            "description": "Desc"
        }
        response = client.post("/features", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["parent_feature_id"] == parent.id

    def test_update_feature_invalid_parent(self, client):
        project = baker.make("projects.Project")
        feature = baker.make("projects.Feature", project=project)
        # Try to make it its own parent
        payload = {
            "project_id": project.id,
            "parent_feature_id": feature.id,
            "name": "Updated",
            "description": "Desc"
        }
        response = client.put(f"/features/{feature.id}", json=payload)
        assert response.status_code == 400
        assert "A feature cannot be its own parent." in response.json()["detail"]
