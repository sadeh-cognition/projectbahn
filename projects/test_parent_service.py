import pytest
from ninja.errors import HttpError
from model_bakery import baker
from projects.services.parent import validate_parent_feature

@pytest.mark.django_db
class TestValidateParentFeature:
    def test_no_parent_feature(self):
        project = baker.make("projects.Project")
        validate_parent_feature(project=project, parent_feature=None)
        # Should not raise

    def test_same_feature_as_parent(self):
        project = baker.make("projects.Project")
        feature = baker.make("projects.Feature", project=project)
        with pytest.raises(HttpError) as exc:
            validate_parent_feature(project=project, parent_feature=feature, feature_id=feature.id)
        assert exc.value.status_code == 400
        assert "A feature cannot be its own parent." in str(exc.value)

    def test_different_project(self):
        project1 = baker.make("projects.Project")
        project2 = baker.make("projects.Project")
        feature = baker.make("projects.Feature", project=project2)
        with pytest.raises(HttpError) as exc:
            validate_parent_feature(project=project1, parent_feature=feature)
        assert exc.value.status_code == 400
        assert "Parent feature must belong to the same project." in str(exc.value)

    def test_ancestor_loop(self):
        project = baker.make("projects.Project")
        feature1 = baker.make("projects.Feature", project=project)
        feature2 = baker.make("projects.Feature", project=project, parent_feature=feature1)
        
        # Trying to set feature2 as parent of feature1
        with pytest.raises(HttpError) as exc:
            validate_parent_feature(project=project, parent_feature=feature2, feature_id=feature1.id)
        assert exc.value.status_code == 400
        assert "A feature cannot be assigned to its own descendant." in str(exc.value)

    def test_valid_parent(self):
        project = baker.make("projects.Project")
        feature1 = baker.make("projects.Feature", project=project)
        feature2 = baker.make("projects.Feature", project=project)
        validate_parent_feature(project=project, parent_feature=feature1, feature_id=feature2.id)
        # Should not raise
