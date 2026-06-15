"""RQ2 minimal-profile mode tests.

Candidate terms are suggestions, not review obligations. In the default
``minimal`` mode each approved requirement contributes one primary, reuse-first
profile action; ``exploratory`` mode generates every candidate action. These
tests pin the selection/ranking contract and the reduction/reuse/extension
metrics that keep the generated application profile minimal.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / 'requirement-reuse-service'
sys.path.insert(0, str(SERVICE_ROOT))

from requirement_reuse_service.models import (  # noqa: E402
    CandidateMetadataAction,
    CandidateRequirement,
    ConstraintHint,
    GenerateProfileChangesRequest,
    NormalizedIntent,
    SourceEvidence,
)
from requirement_reuse_service.profile_generation import generate_profile_changes  # noqa: E402


def make_requirement(
    requirement_id: str,
    terms: list[str],
    *,
    action: str = 'reuse_existing_term',
    resource: str = 'Dataset',
    obligation: str = 'recommended',
    value_kind: str = 'uri',
    requires_multiple_elements: bool = False,
    status: str = 'approved',
    metadata_need: str | None = None,
    statement: str | None = None,
) -> CandidateRequirement:
    need = metadata_need or f'metadata need {requirement_id}'
    return CandidateRequirement(
        id=requirement_id,
        normalized_statement=statement or f'A dcat:{resource} should satisfy {requirement_id}.',
        requirement_type='access_policy',
        requirement_scope='profile_element',
        status=status,  # type: ignore[arg-type]
        validation_status='valid',
        requires_multiple_elements=requires_multiple_elements,
        source_evidence=[
            SourceEvidence(
                evidence_unit_id=f'ev-{requirement_id}',
                source_id='src-1',
                artifact_name='stakeholder-needs.md',
                artifact_kind='text',
                evidence_text=f'evidence for {requirement_id}',
            )
        ],
        normalized_intent=NormalizedIntent(
            resource_type=resource,  # type: ignore[arg-type]
            metadata_need=need,
            value_kind=value_kind,  # type: ignore[arg-type]
            obligation_hint=obligation,  # type: ignore[arg-type]
        ),
        candidate_metadata_actions=[
            CandidateMetadataAction(
                action=action,  # type: ignore[arg-type]
                target_class=resource,
                candidate_terms=terms,
                rationale=f'rationale for {requirement_id}',
                constraint_hint=ConstraintHint(value_kind=value_kind, obligation=obligation),  # type: ignore[arg-type]
            )
        ],
    )


def changes_for(requirements, mode='minimal', **kwargs):
    return generate_profile_changes(
        GenerateProfileChangesRequest(requirements=requirements, mode=mode, **kwargs)
    )


# --- 1: multiple candidate terms -> one highest-ranked reusable action --------


def test_minimal_mode_selects_only_highest_ranked_reusable_action():
    # The requirement suggests an extension AND a reusable standard term.
    change_set = changes_for([make_requirement('R1', terms=['cx:customLicenseThing', 'dcterms:license'])])

    assert len(change_set.changes) == 1
    change = change_set.changes[0]
    assert change.change_type == 'reuse_property'  # reuse beats extension
    assert change.slot_name == 'license'
    assert change.term_uri == 'http://purl.org/dc/terms/license'
    assert change.selected is True
    # the discarded suggestion is preserved, not dropped
    assert 'cx:customLicenseThing' in change.alternative_terms
    assert set(change_set.discovered_candidate_terms) == {'cx:customLicenseThing', 'dcterms:license'}


def test_semantic_fit_selects_license_over_generic_keyword():
    requirement = make_requirement(
        'R-license-fit',
        terms=['dcat:keyword', 'dcterms:license'],
        metadata_need='describe license and reuse policy',
        statement='A dcat:Dataset should expose license and reuse policy metadata for access assessment.',
    )

    change_set = changes_for([requirement])

    assert len(change_set.changes) == 1
    assert change_set.changes[0].slot_name == 'license'
    assert 'dcat:keyword' in change_set.changes[0].alternative_terms


def test_semantic_fit_allows_specific_extension_over_generic_identifier():
    requirement = make_requirement(
        'R-aas-fit',
        terms=['dcterms:identifier', 'cx:hasAASSubmodel'],
        action='reuse_existing_term',
        metadata_need='reference represented AAS submodels',
        statement='A dcat:Dataset should indicate which AAS submodels are represented by the dataset.',
    )

    change_set = changes_for([requirement])

    assert len(change_set.changes) == 1
    assert change_set.changes[0].slot_name == 'hasAASSubmodel'
    assert change_set.changes[0].change_type == 'create_extension_property'
    assert 'dcterms:identifier' in change_set.changes[0].alternative_terms


# --- 2: two requirements, same term -> one ProfileChange, both ids ------------


def test_two_requirements_same_term_merge_into_one_change():
    change_set = changes_for(
        [
            make_requirement('R1', terms=['dcterms:license'], obligation='recommended'),
            make_requirement('R2', terms=['dcterms:license'], obligation='mandatory'),
        ]
    )

    assert len(change_set.changes) == 1
    change = change_set.changes[0]
    assert set(change.source_requirement_ids) == {'R1', 'R2'}
    assert {'ev-R1', 'ev-R2'} <= set(change.evidence_ids)
    assert change.obligation_level == 'mandatory'  # strongest obligation wins
    assert change_set.summary_metrics['requirements_addressed_count'] == 2


# --- 3: extension only when no suitable reused term exists --------------------


def test_extension_selected_only_when_no_reusable_term_available():
    change_set = changes_for(
        [
            make_requirement('R-reuse', terms=['dcterms:license', 'cx:altLicense']),
            make_requirement('R-ext', action='create_extension', terms=['cx:hasAASSubmodel']),
        ]
    )

    by_requirement = {change.requirement_id: change for change in change_set.changes}
    # a reusable standard term was available -> extension NOT selected
    assert by_requirement['R-reuse'].change_type == 'reuse_property'
    # no reusable term available -> extension selected
    assert by_requirement['R-ext'].change_type == 'create_extension_property'
    assert by_requirement['R-ext'].term_uri == 'https://w3id.org/cx#hasAASSubmodel'
    assert change_set.summary_metrics['extension_rate'] == 0.5
    assert change_set.summary_metrics['reuse_rate'] == 0.5


# --- 4: exploratory mode preserves all candidate terms/actions ---------------


def test_exploratory_mode_preserves_all_candidate_terms():
    requirement = make_requirement('R1', terms=['dcat:keyword', 'dcterms:license', 'cx:custom'])

    minimal = changes_for([requirement])
    exploratory = changes_for([requirement], mode='exploratory')

    assert len(minimal.changes) == 1  # one primary action
    assert {change.slot_name for change in exploratory.changes} == {'keyword', 'license', 'custom'}
    assert len(exploratory.changes) == 3  # nothing filtered away
    assert exploratory.mode == 'exploratory'
    # exactly one change is flagged as the minimal pick
    assert sum(1 for change in exploratory.changes if change.selected) == 1


# --- requires_multiple_elements escape hatch ---------------------------------


def test_requires_multiple_elements_keeps_best_per_slot():
    terms = ['dcterms:title', 'dcterms:description']
    single = changes_for([make_requirement('R1', terms=terms)])
    multiple = changes_for([make_requirement('R1', terms=terms, requires_multiple_elements=True)])

    assert len(single.changes) == 1
    assert {change.slot_name for change in multiple.changes} == {'title', 'description'}


# --- summary metrics ---------------------------------------------------------


def test_summary_metrics_report_reduction_and_reuse():
    change_set = changes_for(
        [
            make_requirement('R1', terms=['dcat:keyword', 'dcterms:license', 'cx:custom']),
            make_requirement('R2', action='create_extension', terms=['cx:hasAASSubmodel']),
        ]
    )
    metrics = change_set.summary_metrics

    for key in (
        'discovered_candidate_term_count',
        'selected_profile_change_count',
        'reduction_rate',
        'reuse_rate',
        'extension_rate',
        'requirements_addressed_count',
        'average_profile_changes_per_requirement',
    ):
        assert key in metrics, f'missing metric: {key}'

    # 4 distinct candidate terms discovered, 2 selected (one per requirement)
    assert metrics['discovered_candidate_term_count'] == 4
    assert metrics['selected_profile_change_count'] == 2
    assert metrics['reduction_rate'] == 0.5
    assert metrics['requirements_addressed_count'] == 2
    assert metrics['average_profile_changes_per_requirement'] == 1.0
    assert metrics['mode'] == 'minimal'


def test_minimal_mode_is_default():
    change_set = generate_profile_changes(
        GenerateProfileChangesRequest(requirements=[make_requirement('R1', terms=['dcterms:license'])])
    )
    assert change_set.mode == 'minimal'
