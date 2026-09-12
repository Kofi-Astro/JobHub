"""Keyword classifier: seeded taxonomy + sample jobs → expected sub-field."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.categorization.classifier import Classifier
from app.models import Subfield
from app.models.enums import CategorizationMethod


@pytest.fixture
def classifier(seeded) -> Classifier:
    return Classifier.from_db(seeded)


def _slug_of(db, subfield_id) -> str | None:
    if subfield_id is None:
        return None
    return db.scalar(select(Subfield.slug).where(Subfield.id == subfield_id))


@pytest.mark.parametrize(
    ("title", "description", "expected_slug"),
    [
        (
            "Senior React Developer",
            "Build our frontend in React and TypeScript.",
            "web-development",
        ),
        ("Registered Nurse - ICU", "Provide bedside care in the intensive care unit.", "nursing"),
        ("Line Cook", "Prep and cook on the line for a busy restaurant.", "food-service"),
        ("DevOps Engineer", "Kubernetes, Terraform and CI/CD pipelines on AWS.", "devops"),
        ("Data Scientist", "Build ML models with PyTorch and analyse experiments.", "data-science"),
        ("HGV Driver", "Deliver goods on regional routes, CDL required.", "transportation-driving"),
        ("Security Guard", "Monitor CCTV and patrol the premises overnight.", "security-services"),
    ],
)
def test_classifies_clear_cases(classifier, seeded, title, description, expected_slug):
    result = classifier.classify(title, description)
    assert result.method == CategorizationMethod.KEYWORD
    assert _slug_of(seeded, result.subfield_id) == expected_slug
    assert result.field_id is not None
    assert 0.0 < (result.confidence or 0) <= 1.0


def test_abstains_on_ambiguous_or_empty(classifier):
    assert not classifier.classify("Ninja Rockstar Guru", "Join our team!").is_categorized
    assert not classifier.classify("", "").is_categorized
    assert not classifier.classify(None, None).is_categorized


def test_title_hit_outweighs_description_noise(classifier, seeded):
    # "marketing" appears once in the description but the title is unambiguous.
    result = classifier.classify(
        "Plumber",
        "Our marketing team supports the trades division. Install and repair pipes.",
    )
    assert _slug_of(seeded, result.subfield_id) == "plumbing-hvac"


def test_deterministic(classifier):
    a = classifier.classify("Backend Engineer", "Python, FastAPI, PostgreSQL.")
    b = classifier.classify("Backend Engineer", "Python, FastAPI, PostgreSQL.")
    assert a == b
