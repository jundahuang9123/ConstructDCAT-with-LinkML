from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CODEBOOK_PATH = Path(__file__).resolve().parents[1] / 'schema' / 'rq1_codebook.yaml'

DEFAULT_CODEBOOK: dict[str, Any] = {
    'schema_version': 'rq1-codebook-v1',
    'discovery_need_types': [
        'descriptive_metadata',
        'access_and_license',
        'representation_format',
        'schema_or_standard',
        'asset_or_entity_scope',
        'lifecycle_phase',
        'semantic_anchor',
        'quality_or_provenance',
        'spatial_or_project_context',
    ],
    'exclude_as_not_rq1': [
        'internal_instance_data',
        'per_object_attribute',
        'engineering_calculation',
        'geometry_detail',
        'sensor_measurement_value',
        'ontology_class_mirroring',
        'implementation_detail',
    ],
    'allowed_extraction_input': ['source_documents', 'competency_questions', 'user_tasks'],
    'held_out_validation_input': [
        'expert_reference_requirements',
        'expected_answer_set',
        'manually_curated_gold_requirements',
    ],
}


@lru_cache(maxsize=1)
def load_rq1_codebook() -> dict[str, Any]:
    if not CODEBOOK_PATH.exists():
        return DEFAULT_CODEBOOK
    data = yaml.safe_load(CODEBOOK_PATH.read_text(encoding='utf-8')) or {}
    return {**DEFAULT_CODEBOOK, **data}


def codebook_prompt_text() -> str:
    codebook = load_rq1_codebook()
    valid = '\n'.join(f'- {item}' for item in codebook.get('valid_requirement_conditions', []))
    allowed = ', '.join(codebook.get('allowed_extraction_input', []))
    held_out = ', '.join(codebook.get('held_out_validation_input', []))
    discovery = ', '.join(codebook.get('discovery_need_types', []))
    exclusions = ', '.join(codebook.get('exclude_as_not_rq1', []))
    return (
        'RQ1 CODEBOOK\n'
        f'Allowed extraction input: {allowed}.\n'
        f'Held-out validation input, never extraction input: {held_out}.\n'
        f'Valid requirement conditions:\n{valid}\n'
        f'Discovery need categories: {discovery}.\n'
        f'Exclude as not RQ1: {exclusions}.'
    )
