from __future__ import annotations

from copy import deepcopy

import yaml

from minimum_workflow.kb_catalog_validator import DEFAULT_CATALOG_PATH, load_catalog, validate_catalog


def test_current_kb_catalog_is_internally_consistent() -> None:
    catalog = load_catalog(DEFAULT_CATALOG_PATH)

    errors = validate_catalog(catalog)

    assert errors == []


def test_validator_catches_stale_role_index_dataset_id() -> None:
    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    broken = deepcopy(catalog)
    broken["role_index"]["supplier"] = ["b5c8a40d-1ebf-4ada-97c6-be7aba26a40e"]

    errors = validate_catalog(broken)

    assert "role_index.supplier references unknown dataset id: b5c8a40d-1ebf-4ada-97c6-be7aba26a40e" in errors


def test_validator_catches_stale_tier_index_dataset_id() -> None:
    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    broken = deepcopy(catalog)
    broken["tier_index"]["A"][0] = "b5c8a40d-1ebf-4ada-97c6-be7aba26a40e"

    errors = validate_catalog(broken)

    assert "tier_index.A references unknown dataset id: b5c8a40d-1ebf-4ada-97c6-be7aba26a40e" in errors


def test_catalog_retrieval_defaults_are_exposed_for_downstream_loaders() -> None:
    catalog = load_catalog(DEFAULT_CATALOG_PATH)
    dumped = yaml.safe_dump(catalog, allow_unicode=True)

    assert catalog["retrieval_defaults"]["search_method"] == "hybrid_search"
    assert catalog["retrieval_defaults"]["reranking_enable"] is True
    assert catalog["retrieval_defaults"]["score_threshold_enabled"] is False
    assert "retrieval_defaults" in dumped
