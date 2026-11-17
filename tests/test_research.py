import pytest

from integrity.research import FEATURES, FEATURE_SCHEMA, profile, require_compatible, split_integrity

pd = pytest.importorskip("pandas")


def test_account_leakage_check():
    labels = pd.DataFrame({"id": ["u1", "u2", "u3"], "label": ["human", "bot", "human"]})
    splits = pd.DataFrame({"id": ["u1", "u2", "u3"], "split": ["train", "valid", "test"]})
    assert len(split_integrity(labels, splits)) == 3
    duplicate = pd.concat([splits, pd.DataFrame({"id": ["u1"], "split": ["test"]})])
    with pytest.raises(ValueError, match="leak"):
        split_integrity(labels, duplicate)


def test_model_domain_provenance_and_schema_check():
    manifest = {"platform": "twitter", "feature_schema": FEATURE_SCHEMA, "features": list(FEATURES),
                "evaluation_kind": "labeled_research"}
    require_compatible(manifest, "twitter", FEATURE_SCHEMA, FEATURES)
    with pytest.raises(ValueError):
        require_compatible(manifest, "bluesky", FEATURE_SCHEMA, FEATURES)
    with pytest.raises(ValueError):
        require_compatible(manifest, "twitter", FEATURE_SCHEMA, list(reversed(FEATURES)))
    with pytest.raises(ValueError):
        require_compatible({**manifest, "evaluation_kind": "synthetic"}, "twitter", FEATURE_SCHEMA, FEATURES)
    assert all(value is None for value in profile({}).values())
