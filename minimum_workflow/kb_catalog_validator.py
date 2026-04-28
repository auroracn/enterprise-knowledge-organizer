from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "kb_catalog.yaml"
VALID_TIERS = {"A", "B", "C"}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def load_catalog(catalog_path: Path | str = DEFAULT_CATALOG_PATH) -> dict[str, Any]:
    path = Path(catalog_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"catalog must be a mapping: {path}")
    return payload


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    datasets = _as_list(catalog.get("datasets"))
    dataset_ids: set[str] = set()
    dataset_tiers: dict[str, str] = {}
    duplicate_ids: set[str] = set()

    for index, dataset in enumerate(datasets, 1):
        if not isinstance(dataset, dict):
            errors.append(f"datasets[{index}] must be a mapping")
            continue
        dataset_id = str(dataset.get("id") or "").strip()
        name = str(dataset.get("name") or "").strip()
        tier = str(dataset.get("tier") or "").strip()
        if not dataset_id:
            errors.append(f"datasets[{index}] is missing id")
            continue
        if dataset_id in dataset_ids:
            duplicate_ids.add(dataset_id)
        dataset_ids.add(dataset_id)
        dataset_tiers[dataset_id] = tier
        if not name:
            errors.append(f"dataset {dataset_id} is missing name")
        if tier not in VALID_TIERS:
            errors.append(f"dataset {dataset_id} has invalid tier: {tier or '<empty>'}")

    for dataset_id in sorted(duplicate_ids):
        errors.append(f"duplicate dataset id: {dataset_id}")

    role_index = catalog.get("role_index") or {}
    if not isinstance(role_index, dict):
        errors.append("role_index must be a mapping")
    else:
        for role, ids in role_index.items():
            for dataset_id in _as_list(ids):
                dataset_id = str(dataset_id).strip()
                if dataset_id not in dataset_ids:
                    errors.append(f"role_index.{role} references unknown dataset id: {dataset_id}")

    tier_index = catalog.get("tier_index") or {}
    if not isinstance(tier_index, dict):
        errors.append("tier_index must be a mapping")
    else:
        indexed_by_tier: dict[str, set[str]] = {tier: set() for tier in VALID_TIERS}
        for tier, ids in tier_index.items():
            tier_name = str(tier).strip()
            if tier_name not in VALID_TIERS:
                errors.append(f"tier_index has invalid tier: {tier_name or '<empty>'}")
                continue
            for dataset_id in _as_list(ids):
                dataset_id = str(dataset_id).strip()
                if dataset_id not in dataset_ids:
                    errors.append(f"tier_index.{tier_name} references unknown dataset id: {dataset_id}")
                    continue
                indexed_by_tier[tier_name].add(dataset_id)
                expected_tier = dataset_tiers.get(dataset_id)
                if expected_tier != tier_name:
                    errors.append(
                        f"tier_index.{tier_name} contains {dataset_id}, but dataset tier is {expected_tier}"
                    )
        indexed_ids = set().union(*indexed_by_tier.values())
        for dataset_id in sorted(dataset_ids - indexed_ids):
            errors.append(f"dataset {dataset_id} is missing from tier_index.{dataset_tiers.get(dataset_id)}")

    retrieval_defaults = catalog.get("retrieval_defaults") or {}
    if retrieval_defaults and not isinstance(retrieval_defaults, dict):
        errors.append("retrieval_defaults must be a mapping")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate kb_catalog.yaml internal consistency.")
    parser.add_argument("catalog", nargs="?", default=str(DEFAULT_CATALOG_PATH))
    args = parser.parse_args(argv)

    catalog_path = Path(args.catalog)
    errors = validate_catalog(load_catalog(catalog_path))
    if errors:
        print(f"[FAIL] {catalog_path}")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"[OK] {catalog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
