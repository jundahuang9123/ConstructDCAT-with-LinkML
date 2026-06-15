import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / 'requirement-reuse-service'
sys.path.insert(0, str(SERVICE_ROOT))

from requirement_reuse_service.llm.client import LLMError, MockLLMClient, extract_json_object  # noqa: E402
from requirement_reuse_service.llm.extractor import (  # noqa: E402
    LLMExtractionResult,
    PROMPT_VERSION,
    build_user_prompt,
    extract_with_llm,
    merge_hybrid,
)
from requirement_reuse_service.llm import LLMConfig, create_client  # noqa: E402
from requirement_reuse_service.models import AnalysisRequest, EvidenceUnit, RequirementSetSaveRequest, UserTask  # noqa: E402
from requirement_reuse_service.registry import load_requirement_set, save_requirement_set  # noqa: E402
from requirement_reuse_service.service import analyze_payload, export_rq1_dataset, extract_evidence_units, term_catalog  # noqa: E402


SOURCE_TEXT = (
    'Each dataset must carry a license or access rights statement. '
    'Datasets exchanged in the dataspace should reference the AAS submodels they represent.'
)


def evidence_unit_id_for(quote: str) -> str:
    for unit in extract_evidence_units(AnalysisRequest(text=SOURCE_TEXT)):
        if quote in unit.content or quote.split()[0] in unit.content:
            return unit.id
    raise AssertionError(f'No evidence unit found for quote: {quote}')


def llm_payload(
    quote: str,
    evidence_unit_id: str | None = None,
    task_ids: list[str] | None = None,
    action: str = 'reuse_existing_term',
    candidate_terms: list[str] | None = None,
) -> dict:
    return {
        'requirements': [
            {
                'statement': 'A dcat:Dataset must carry a license or access rights statement.',
                'requirement_type': 'access_policy',
                'requirement_scope': 'profile_element',
                'resource_type': 'Dataset',
                'metadata_need': 'describe access and reuse conditions',
                'value_kind': 'uri',
                'obligation': 'mandatory',
                'fair_dimensions': ['A', 'R'],
                'fair_rationale': 'License metadata enables reuse decisions and access assessment.',
                'action': action,
                'candidate_terms': candidate_terms or ['dcterms:license', 'dcterms:accessRights'],
                'action_rationale': 'dcterms covers this need; no extension required.',
                'supports_user_tasks': task_ids or [],
                'evidence': [{'evidence_unit_id': evidence_unit_id or evidence_unit_id_for('Each dataset'), 'quote': quote}],
                'confidence': 0.85,
            }
        ]
    }


def test_llm_extraction_produces_traceable_verified_requirement():
    client = MockLLMClient(llm_payload('Each dataset must carry a license or access rights statement.'))
    request = AnalysisRequest(text=SOURCE_TEXT, strategy='llm')

    requirements, warnings = extract_with_llm(request, client)

    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement.requirement_type == 'access_policy'
    assert requirement.requirement_scope == 'profile_element'
    assert requirement.validation_status == 'valid'
    assert requirement.status == 'candidate'
    assert requirement.source_evidence and 'chars:' in requirement.source_evidence[0].locator
    assert requirement.provenance is not None
    assert requirement.provenance.strategy == 'llm'
    assert requirement.provenance.prompt_version == PROMPT_VERSION
    assert requirement.provenance.evidence_verified is True
    assert not warnings


def test_hallucinated_quote_is_discarded_and_requirement_flagged():
    client = MockLLMClient(llm_payload('Datasets must include a fabricated quality score of 9000.'))
    request = AnalysisRequest(text=SOURCE_TEXT, strategy='llm')

    requirements, warnings = extract_with_llm(request, client)

    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement.source_evidence == []
    assert requirement.status == 'candidate'
    assert requirement.validation_status == 'missing_evidence'
    assert requirement.provenance.evidence_verified is False
    assert requirement.confidence <= 0.4
    assert any('Discarded unverifiable evidence' in warning for warning in warnings)


def test_whitespace_differences_do_not_fail_verification():
    quote = 'Each  dataset must\ncarry a license or access rights statement.'
    client = MockLLMClient(llm_payload(quote))
    requirements, warnings = extract_with_llm(AnalysisRequest(text=SOURCE_TEXT, strategy='llm'), client)
    assert requirements[0].provenance.evidence_verified is True
    assert not warnings


def test_user_task_links_are_validated_against_known_tasks():
    tasks = [UserTask(id='cq-1', statement='Which datasets can be reused under an open license?')]
    client = MockLLMClient(
        llm_payload('Each dataset must carry a license or access rights statement.', task_ids=['cq-1', 'cq-bogus'])
    )
    request = AnalysisRequest(text=SOURCE_TEXT, strategy='llm', user_tasks=tasks)

    requirements, warnings = extract_with_llm(request, client)

    assert requirements[0].supports_user_tasks == ['cq-1']
    assert any('cq-bogus' in warning for warning in warnings)


def test_analyze_payload_llm_strategy_falls_back_to_rules_without_provider(monkeypatch):
    for variable in ['RRS_LLM_PROVIDER', 'RRS_LLM_BASE_URL', 'RRS_LLM_MODEL', 'ANTHROPIC_API_KEY']:
        monkeypatch.delenv(variable, raising=False)

    response = analyze_payload(AnalysisRequest(text=SOURCE_TEXT, strategy='llm'))

    assert response.strategy == 'rules'
    assert response.requirements  # rule-based results still delivered
    assert any('LLM extraction unavailable' in warning for warning in response.warnings)


def test_mock_provider_only_runs_when_explicitly_configured(monkeypatch):
    for variable in ['RRS_LLM_PROVIDER', 'RRS_LLM_BASE_URL', 'RRS_LLM_MODEL', 'ANTHROPIC_API_KEY']:
        monkeypatch.delenv(variable, raising=False)
    config = LLMConfig.from_env()
    assert config.provider == 'disabled'
    with pytest.raises(LLMError):
        create_client(config)

    monkeypatch.setenv('RRS_LLM_PROVIDER', 'mock')
    client = create_client(LLMConfig.from_env())
    assert client.describe()['provider'] == 'mock'


def test_unknown_evidence_unit_id_is_flagged():
    client = MockLLMClient(llm_payload('Each dataset must carry a license or access rights statement.', evidence_unit_id='ev-missing'))
    requirements, warnings = extract_with_llm(AnalysisRequest(text=SOURCE_TEXT, strategy='llm'), client)

    assert requirements[0].source_evidence == []
    assert requirements[0].validation_status == 'missing_evidence'
    assert any('unknown evidence_unit_id=ev-missing' in warning for warning in warnings)


def test_unknown_reused_term_is_flagged():
    client = MockLLMClient(
        llm_payload('Each dataset must carry a license or access rights statement.', candidate_terms=['dcat:notARealTerm'])
    )
    requirements, _ = extract_with_llm(AnalysisRequest(text=SOURCE_TEXT, strategy='llm'), client)

    assert requirements[0].validation_status == 'unknown_term'
    assert requirements[0].confidence <= 0.55


def test_create_extension_with_standard_or_bad_prefix_is_flagged():
    standard = MockLLMClient(
        llm_payload('Each dataset must carry a license or access rights statement.', action='create_extension', candidate_terms=['dcterms:title'])
    )
    bad_prefix = MockLLMClient(
        llm_payload('Each dataset must carry a license or access rights statement.', action='create_extension', candidate_terms=['bad:license'])
    )

    standard_requirements, _ = extract_with_llm(AnalysisRequest(text=SOURCE_TEXT, strategy='llm'), standard)
    bad_prefix_requirements, _ = extract_with_llm(AnalysisRequest(text=SOURCE_TEXT, strategy='llm'), bad_prefix)

    assert standard_requirements[0].validation_status == 'needs_review'
    assert bad_prefix_requirements[0].validation_status == 'needs_review'


def test_analyze_payload_rules_strategy_stamps_provenance_and_links_tasks():
    tasks = [UserTask(id='cq-license', statement='Which datasets can be reused under an open license for analytics?')]
    response = analyze_payload(AnalysisRequest(text=SOURCE_TEXT, strategy='rules', user_tasks=tasks))

    assert response.strategy == 'rules'
    assert response.user_tasks == tasks
    assert all(requirement.provenance and requirement.provenance.strategy == 'rules' for requirement in response.requirements)
    assert any(requirement.supports_user_tasks for requirement in response.requirements)


def test_hybrid_merge_keeps_llm_first_and_adds_novel_rule_requirements():
    client = MockLLMClient(llm_payload('Each dataset must carry a license or access rights statement.'))
    request = AnalysisRequest(text=SOURCE_TEXT, strategy='llm')
    llm_requirements, _ = extract_with_llm(request, client)
    rules_response = analyze_payload(AnalysisRequest(text=SOURCE_TEXT, strategy='rules'))

    merged = merge_hybrid(llm_requirements, rules_response.requirements)

    assert merged[0].provenance.strategy == 'llm'
    assert len(merged) > 1  # rule-based records covering other needs were appended
    needs = [requirement.normalized_intent.metadata_need for requirement in merged]
    assert len(needs) == len(set(needs)) or len(merged) >= len(llm_requirements)


def test_requirement_set_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv('RRS_REQUIREMENT_STORE', str(tmp_path))
    response = analyze_payload(AnalysisRequest(text=SOURCE_TEXT, strategy='rules'))

    info = save_requirement_set(RequirementSetSaveRequest(name='Pilot Run', analysis=response))
    loaded = load_requirement_set(info.id)

    assert loaded is not None
    assert loaded.name == 'Pilot Run'
    assert len(loaded.requirements) == info.requirement_count == len(response.requirements)
    assert loaded.requirements[0].provenance is not None


def test_rq1_export_includes_evidence_units_and_duplicate_groups():
    export = export_rq1_dataset(AnalysisRequest(text=SOURCE_TEXT, strategy='rules'))

    assert export['schema_version'] == 'rq1-requirement-dataset-v1'
    assert export['requirements']
    assert export['evidence_units']
    assert 'duplicate_groups' in export
    assert 'review_editor_history' in export
    assert export['summary_metrics']['evidence_unit_count'] == len(export['evidence_units'])
    assert 'rq1_codebook' in export
    assert 'funnel_metrics' in export


def test_rq1_validation_uses_shared_rq2_term_registry():
    catalog = term_catalog()
    for term in ['dcat:landingPage', 'dcterms:language', 'dcterms:spatial', 'foaf:name', 'prov:wasAttributedTo']:
        assert term in catalog


def test_llm_prompt_reports_truncated_and_omitted_evidence_units():
    units = [
        EvidenceUnit(
            id=f'ev-{index}',
            source_id='src',
            artifact_name='large.txt',
            artifact_kind='text',
            content='license ' + ('x' * 5000),
            extracted_facts=['Large source chunk'],
        )
        for index in range(70)
    ]

    prompt, warnings = build_user_prompt(units, [])

    assert 'RQ1 CODEBOOK' in prompt
    assert 'Held-out validation input' in prompt
    assert any('input_budget_truncation' in warning for warning in warnings)
    assert any('input_budget_omission' in warning for warning in warnings)


def test_mock_client_rejects_payload_that_violates_schema():
    client = MockLLMClient({'requirements': [{'statement': 123}]})
    with pytest.raises(LLMError):
        client.generate_structured(system='s', user='u', output_model=LLMExtractionResult)


def test_extract_json_object_handles_fences_and_prose():
    fenced = '```json\n{"requirements": []}\n```'
    assert extract_json_object(fenced) == '{"requirements": []}'
    prose = 'Here is the result: {"requirements": []} hope that helps'
    assert extract_json_object(prose) == '{"requirements": []}'
