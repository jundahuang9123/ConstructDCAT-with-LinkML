from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from typing import Any, Iterable

from datetime import datetime, timezone

from rdflib import Graph

from .models import (
    AnalysisRequest,
    AnalysisResponse,
    ArtifactPayload,
    ArtifactSummary,
    CandidateMetadataAction,
    CandidateRequirement,
    CompetencyQuestion,
    DuplicateGroup,
    EvidenceUnit,
    ExtractedAttribute,
    ExtractionProvenance,
    NormalizedIntent,
    SourceEvidence,
    ConstraintGenerationRequest,
    ConstraintGenerationResponse,
    MetadataCandidate,
    RecommendationRequest,
    RecommendationResponse,
    ReuseRecommendation,
    SemanticCandidate,
    UserTask,
)
from .rq1_codebook import load_rq1_codebook
from .term_registry import (
    TERMS as RQ2_TERMS,
    compact as compact_registry_uri,
    domain_compatible as rq2_domain_compatible,
    normalize_resource_type as normalize_registry_resource,
)


TEXT_RULES = [
    {
        'category': 'Dataset Metadata',
        'title': 'Describe datasets with reusable catalog metadata',
        'description': 'The artifact asks for dataset-level description, title, keywords, publisher, or thematic metadata.',
        'tokens': ['title', 'description', 'describe', 'keyword', 'theme', 'publisher', 'catalog', 'dataset metadata'],
        'properties': ['title', 'description', 'keyword', 'theme', 'publisher'],
    },
    {
        'category': 'Semantic Anchors',
        'title': 'Provide semantic anchors to external concepts',
        'description': 'The artifact refers to semantic IDs, ontology concepts, controlled terms, AAS submodels, IFC entities, or SKOS concepts.',
        'tokens': ['semantic', 'ontology', 'vocabulary', 'concept', 'skos', 'aas', 'submodel', 'semanticid', 'semantic id', 'ifc', 'bot'],
        'properties': ['semanticAnchor', 'usesOntology'],
    },
    {
        'category': 'Asset Semantics',
        'title': 'Capture construction asset semantics',
        'description': 'The artifact mentions construction assets, element types, systems, sensors, spaces, or equipment.',
        'tokens': ['wall', 'hvac', 'pump', 'sensor', 'asset', 'building element', 'space', 'zone', 'equipment', 'component'],
        'properties': ['describesAssetType'],
    },
    {
        'category': 'Lifecycle Information',
        'title': 'Represent construction lifecycle context',
        'description': 'The artifact indicates lifecycle phases such as design, construction, operation, or maintenance.',
        'tokens': ['planning', 'design', 'construction', 'operation', 'maintenance', 'demolition', 'lifecycle', 'life cycle'],
        'properties': ['hasLifecyclePhase'],
    },
    {
        'category': 'Technical Metadata',
        'title': 'Expose technical representation details',
        'description': 'The artifact asks for format, media type, schema version, distribution, or downloadable representation metadata.',
        'tokens': ['format', 'schema version', 'version', 'media type', 'download', 'distribution', 'json', 'rdf', 'ttl', 'ifc file', 'csv'],
        'properties': ['distribution', 'format', 'mediaType', 'schemaVersion', 'downloadURL'],
    },
    {
        'category': 'Access/Policy',
        'title': 'Capture access and policy conditions',
        'description': 'The artifact mentions license, rights, access URL, access rights, policy, or usage constraints.',
        'tokens': ['license', 'rights', 'access', 'policy', 'permission', 'restricted', 'usage'],
        'properties': ['license', 'accessRights', 'accessURL'],
    },
    {
        'category': 'Quality Metadata',
        'title': 'Capture provenance and quality metadata',
        'description': 'The artifact asks for provenance, completeness, confidence, quality, or source system information.',
        'tokens': ['provenance', 'complete', 'completeness', 'quality', 'confidence', 'source system', 'origin'],
        'properties': ['provenance', 'quality', 'hasDataSourceSystem'],
    },
]


PROPERTY_CATALOG: dict[str, dict[str, Any]] = {
    'title': {'label': 'Title', 'uri': 'http://purl.org/dc/terms/title', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'string', 'level': 'mandatory', 'priority': 1},
    'description': {'label': 'Description', 'uri': 'http://purl.org/dc/terms/description', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'string', 'level': 'recommended', 'priority': 1},
    'keyword': {'label': 'Keyword', 'uri': 'http://www.w3.org/ns/dcat#keyword', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'string', 'level': 'recommended', 'priority': 1},
    'theme': {'label': 'Theme', 'uri': 'http://www.w3.org/ns/dcat#theme', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'SkosConcept', 'level': 'recommended', 'priority': 1},
    'publisher': {'label': 'Publisher', 'uri': 'http://purl.org/dc/terms/publisher', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'FoafAgent', 'level': 'recommended', 'priority': 1},
    'distribution': {'label': 'Distribution', 'uri': 'http://www.w3.org/ns/dcat#distribution', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'DcatDistribution', 'level': 'recommended', 'priority': 1},
    'accessURL': {'label': 'Access URL', 'uri': 'http://www.w3.org/ns/dcat#accessURL', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'anyURI', 'level': 'mandatory', 'priority': 1},
    'downloadURL': {'label': 'Download URL', 'uri': 'http://www.w3.org/ns/dcat#downloadURL', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'anyURI', 'level': 'recommended', 'priority': 1},
    'mediaType': {'label': 'Media type', 'uri': 'http://www.w3.org/ns/dcat#mediaType', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'string', 'level': 'recommended', 'priority': 1},
    'format': {'label': 'Format', 'uri': 'http://purl.org/dc/terms/format', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'string', 'level': 'recommended', 'priority': 1},
    'license': {'label': 'License', 'uri': 'http://purl.org/dc/terms/license', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'anyURI', 'level': 'recommended', 'priority': 1},
    'accessRights': {'label': 'Access rights', 'uri': 'http://purl.org/dc/terms/accessRights', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'string', 'level': 'recommended', 'priority': 1},
    'provenance': {'label': 'Provenance', 'uri': 'http://purl.org/dc/terms/provenance', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'string', 'level': 'optional', 'priority': 1},
    'semanticAnchor': {'label': 'Semantic anchor', 'uri': 'https://w3id.org/cx#semanticAnchor', 'vocabulary': 'Construct-DCAT', 'range': 'SemanticAnchor', 'level': 'mandatory', 'priority': 2},
    'usesOntology': {'label': 'Uses ontology', 'uri': 'https://w3id.org/cx#usesOntology', 'vocabulary': 'Construct-DCAT', 'range': 'anyURI', 'level': 'recommended', 'priority': 2},
    'hasLifecyclePhase': {'label': 'Lifecycle phase', 'uri': 'https://w3id.org/cx#hasLifecyclePhase', 'vocabulary': 'Construct-DCAT', 'range': 'LifecyclePhaseEnum', 'level': 'recommended', 'priority': 2},
    'describesAssetType': {'label': 'Describes asset type', 'uri': 'https://w3id.org/cx#describesAssetType', 'vocabulary': 'Construct-DCAT', 'range': 'ConstructionAsset', 'level': 'recommended', 'priority': 2},
    'hasAASSubmodel': {'label': 'AAS submodel anchor', 'uri': 'https://w3id.org/cx#hasAASSubmodel', 'vocabulary': 'AAS/Construct-DCAT', 'range': 'anyURI', 'level': 'recommended', 'priority': 3},
    'hasIFCEntity': {'label': 'IFC entity anchor', 'uri': 'https://w3id.org/cx#hasIFCEntity', 'vocabulary': 'IFC/Construct-DCAT', 'range': 'anyURI', 'level': 'recommended', 'priority': 3},
    'schemaVersion': {'label': 'Conforms to schema/version', 'uri': 'http://purl.org/dc/terms/conformsTo', 'vocabulary': 'DCAT/DCAT-AP', 'range': 'anyURI', 'level': 'recommended', 'priority': 1},
    'quality': {'label': 'Quality annotation', 'uri': 'https://w3id.org/cx#qualityAnnotation', 'vocabulary': 'Construct-DCAT extension', 'range': 'string', 'level': 'optional', 'priority': 4},
    'hasDataSourceSystem': {'label': 'Data source system', 'uri': 'https://w3id.org/cx#hasDataSourceSystem', 'vocabulary': 'Construct-DCAT', 'range': 'string', 'level': 'optional', 'priority': 2},
}


COMMON_TERM_CATALOG: dict[str, dict[str, Any]] = {
    'dcat:Catalog': {'resource_types': ['Catalog']},
    'dcat:Dataset': {'resource_types': ['Dataset']},
    'dcat:Distribution': {'resource_types': ['Distribution']},
    'dcat:DataService': {'resource_types': ['DataService']},
    'dcat:theme': {'resource_types': ['Dataset', 'Catalog']},
    'dcat:keyword': {'resource_types': ['Dataset']},
    'dcat:distribution': {'resource_types': ['Dataset']},
    'dcat:accessURL': {'resource_types': ['Distribution']},
    'dcat:downloadURL': {'resource_types': ['Distribution']},
    'dcat:mediaType': {'resource_types': ['Distribution']},
    'dcat:contactPoint': {'resource_types': ['Dataset', 'DataService']},
    'dcterms:title': {'resource_types': ['Catalog', 'Dataset', 'Distribution', 'DataService']},
    'dcterms:description': {'resource_types': ['Catalog', 'Dataset', 'Distribution', 'DataService']},
    'dcterms:publisher': {'resource_types': ['Catalog', 'Dataset', 'DataService']},
    'dcterms:issued': {'resource_types': ['Dataset', 'Distribution']},
    'dcterms:modified': {'resource_types': ['Dataset', 'Distribution']},
    'dcterms:license': {'resource_types': ['Dataset', 'Distribution']},
    'dcterms:rights': {'resource_types': ['Dataset', 'Distribution']},
    'dcterms:accessRights': {'resource_types': ['Dataset', 'Distribution']},
    'dcterms:format': {'resource_types': ['Distribution']},
    'dcterms:conformsTo': {'resource_types': ['Dataset', 'Distribution']},
    'dcterms:provenance': {'resource_types': ['Dataset', 'Distribution']},
    'skos:Concept': {'resource_types': ['Concept']},
    'skos:prefLabel': {'resource_types': ['Concept']},
    'skos:inScheme': {'resource_types': ['Concept']},
    'prov:wasDerivedFrom': {'resource_types': ['Dataset', 'Distribution']},
    'prov:wasGeneratedBy': {'resource_types': ['Dataset', 'Distribution']},
    'foaf:Agent': {'resource_types': ['Agent']},
}


AAS_ATTRIBUTE_KEYS = {
    'id',
    'idshort',
    'semanticid',
    'semanticidlist',
    'modeltype',
    'category',
    'kind',
    'value',
    'valuetype',
    'preferredname',
    'shortname',
    'displayname',
    'description',
    'assetkind',
    'globalassetid',
    'idtype',
}

URI_TO_PROPERTY = {
    'http://purl.org/dc/terms/title': 'title',
    'http://purl.org/dc/terms/description': 'description',
    'http://purl.org/dc/terms/publisher': 'publisher',
    'http://purl.org/dc/terms/license': 'license',
    'http://purl.org/dc/terms/accessRights': 'accessRights',
    'http://purl.org/dc/terms/format': 'format',
    'http://purl.org/dc/terms/conformsTo': 'schemaVersion',
    'http://www.w3.org/ns/dcat#keyword': 'keyword',
    'http://www.w3.org/ns/dcat#theme': 'theme',
    'http://www.w3.org/ns/dcat#distribution': 'distribution',
    'http://www.w3.org/ns/dcat#accessURL': 'accessURL',
    'http://www.w3.org/ns/dcat#downloadURL': 'downloadURL',
    'http://www.w3.org/ns/dcat#mediaType': 'mediaType',
}


def analyze_payload(payload: AnalysisRequest) -> AnalysisResponse:
    """Dispatch analysis to the selected extraction strategy.

    - ``rules``  deterministic keyword/structure heuristics (baseline)
    - ``llm``    LLM-assisted extraction with verbatim-evidence verification
    - ``hybrid`` LLM records first, rule-based records appended for needs the
      LLM missed; duplicate detection surfaces the overlaps for review
    """
    rules_response = analyze_payload_rules(payload)
    if payload.strategy == 'rules':
        return rules_response

    from .llm import LLMConfig, LLMError, create_client
    from .llm.extractor import extract_with_llm, merge_hybrid

    config = LLMConfig.from_env()
    if payload.llm_model:
        config.model = payload.llm_model
    try:
        client = create_client(config)
        llm_requirements, llm_warnings = extract_with_llm(payload, client)
    except LLMError as exc:
        rules_response.warnings.append(f'LLM extraction unavailable; returning rule-based results instead: {exc}')
        return rules_response

    if payload.strategy == 'hybrid':
        requirements = merge_hybrid(llm_requirements, rules_response.requirements)
    else:
        requirements = llm_requirements
    requirements = link_user_tasks(requirements, payload.user_tasks)
    duplicate_groups = detect_duplicate_requirements(requirements)

    return rules_response.model_copy(
        update={
            'strategy': payload.strategy,
            'requirements': requirements,
            'duplicate_groups': duplicate_groups,
            'funnel_metrics': build_funnel_metrics(rules_response.evidence_units, requirements, duplicate_groups),
            'warnings': [*rules_response.warnings, *llm_warnings],
        }
    )


def analyze_payload_rules(payload: AnalysisRequest) -> AnalysisResponse:
    artifacts: list[ArtifactSummary] = []
    legacy_requirements: list[CandidateRequirement] = []
    semantic_candidates: list[SemanticCandidate] = []
    metadata_candidates: list[MetadataCandidate] = []
    competency_questions: list[CompetencyQuestion] = []
    extracted_attributes: list[ExtractedAttribute] = []
    warnings: list[str] = []

    if payload.text and payload.text.strip():
        summary, reqs, sem, meta, questions, attrs = analyze_text('text description', payload.text)
        artifacts.append(summary)
        legacy_requirements.extend(reqs)
        semantic_candidates.extend(sem)
        metadata_candidates.extend(meta)
        competency_questions.extend(questions)
        extracted_attributes.extend(attrs)

    for artifact in payload.artifacts:
        try:
            summary, reqs, sem, meta, questions, attrs = analyze_artifact(artifact)
        except Exception as exc:
            summary = ArtifactSummary(name=artifact.name, kind='unknown', evidence_count=0, notes=[str(exc)])
            reqs, sem, meta, questions, attrs = [], [], [], [], []
            warnings.append(f'{artifact.name}: {exc}')
        artifacts.append(summary)
        legacy_requirements.extend(reqs)
        semantic_candidates.extend(sem)
        metadata_candidates.extend(meta)
        competency_questions.extend(questions)
        extracted_attributes.extend(attrs)

    evidence_units = extract_evidence_units(payload)
    staged_requirements = extract_candidate_requirements(evidence_units)
    upgraded_legacy = [upgrade_legacy_requirement(requirement) for requirement in legacy_requirements]
    requirements = dedupe_requirements([*staged_requirements, *upgraded_legacy])
    requirements = normalize_requirements(requirements)
    requirements = classify_requirements(requirements)
    requirements = assign_fair_dimensions(requirements)
    requirements = suggest_candidate_metadata_actions(requirements)
    requirements = validate_requirements(requirements)
    requirements = stamp_rule_provenance(requirements)
    requirements = link_user_tasks(requirements, payload.user_tasks)
    duplicate_groups = detect_duplicate_requirements(requirements)

    for category in sorted({requirement.category or category_for_requirement_type(requirement.requirement_type) for requirement in requirements}):
        competency_questions.append(generated_question(category, 'requirement workbench'))

    return AnalysisResponse(
        strategy='rules',
        study_setup=study_setup_from_request(payload),
        artifacts=artifacts,
        evidence_units=dedupe_evidence_units(evidence_units),
        extracted_attributes=dedupe_attributes(extracted_attributes),
        requirements=requirements,
        duplicate_groups=duplicate_groups,
        semantic_candidates=dedupe_semantic(semantic_candidates),
        metadata_candidates=dedupe_metadata(metadata_candidates),
        competency_questions=dedupe_questions(competency_questions),
        user_tasks=list(payload.user_tasks),
        funnel_metrics=build_funnel_metrics(evidence_units, requirements, duplicate_groups),
        warnings=warnings,
    )


def stamp_rule_provenance(requirements: list[CandidateRequirement]) -> list[CandidateRequirement]:
    created_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for requirement in requirements:
        if requirement.provenance is None:
            requirement.provenance = ExtractionProvenance(
                strategy='rules',
                extractor='rule-based-v1',
                created_at=created_at,
                evidence_verified=True,
            )
    return requirements


def link_user_tasks(requirements: list[CandidateRequirement], user_tasks: list[UserTask]) -> list[CandidateRequirement]:
    """Lexical fallback linking of requirements to user tasks (rules baseline).

    LLM-extracted requirements arrive with model-proposed links; this only
    fills in links for requirements that have none yet.
    """
    if not user_tasks:
        return requirements

    def stemmed(value: str) -> set[str]:
        tokens = set()
        for token in normalize_tokens(value):
            for suffix in ('ies', 'ing', 'ed', 'es', 's'):
                if token.endswith(suffix) and len(token) - len(suffix) >= 3:
                    token = token[: -len(suffix)]
                    break
            if token.endswith('e') and len(token) >= 4:
                token = token[:-1]
            tokens.add(token)
        return tokens

    task_tokens = {task.id: stemmed(task.statement) for task in user_tasks}
    for requirement in requirements:
        if requirement.supports_user_tasks:
            continue
        statement = ' '.join(
            filter(None, [requirement.normalized_statement, requirement.normalized_intent.metadata_need, requirement.category])
        )
        requirement_tokens = stemmed(statement)
        linked = [
            task.id
            for task in user_tasks
            if task_tokens[task.id]
            and len(requirement_tokens & task_tokens[task.id]) / len(task_tokens[task.id]) >= 0.3
        ]
        requirement.supports_user_tasks = linked
    return requirements


def extract_requirements(payload: AnalysisRequest) -> AnalysisResponse:
    return analyze_payload(payload)


def export_rq1_dataset(payload: AnalysisRequest) -> dict[str, Any]:
    analysis = analyze_payload(payload)
    requirements = analysis.requirements
    return {
        'schema_version': 'rq1-requirement-dataset-v1',
        'export_kind': 'reproducible_run',
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source_corpus_id': payload.source_corpus_id,
        'study_setup': analysis.study_setup,
        'rq1_codebook': load_rq1_codebook(),
        'strategy_requested': payload.strategy,
        'strategy_used': analysis.strategy,
        'summary_metrics': {
            'competency_question_coverage': competency_question_coverage(requirements, analysis.user_tasks),
            'funnel_metrics': analysis.funnel_metrics,
            'requirement_count': len(requirements),
            'evidence_unit_count': len(analysis.evidence_units),
            'duplicate_group_count': len(analysis.duplicate_groups),
            'user_task_count': len(analysis.user_tasks),
            'warning_count': len(analysis.warnings),
            'requirements_by_type': dict(Counter(requirement.requirement_type for requirement in requirements)),
            'requirements_by_scope': dict(Counter(requirement.requirement_scope for requirement in requirements)),
            'requirements_by_validation_status': dict(Counter(requirement.validation_status for requirement in requirements)),
            'requirements_with_editor_history': sum(
                1 for requirement in requirements if requirement.provenance and requirement.provenance.editor_history
            ),
        },
        'requirements': [requirement.model_dump(mode='json', exclude_none=True) for requirement in requirements],
        'evidence_units': [unit.model_dump(mode='json', exclude_none=True) for unit in analysis.evidence_units],
        'duplicate_groups': [group.model_dump(mode='json', exclude_none=True) for group in analysis.duplicate_groups],
        'user_tasks': [task.model_dump(mode='json', exclude_none=True) for task in analysis.user_tasks],
        'funnel_metrics': analysis.funnel_metrics,
        'warnings': analysis.warnings,
        'review_editor_history': [
            {
                'requirement_id': requirement.id,
                'review_status': requirement.status,
                'validation_status': requirement.validation_status,
                'review_notes': requirement.review_notes,
                'editor_history': requirement.provenance.editor_history if requirement.provenance else [],
            }
            for requirement in requirements
        ],
    }


def study_setup_from_request(payload: AnalysisRequest) -> dict[str, Any]:
    codebook = load_rq1_codebook()
    return {
        'source_corpus_id': payload.source_corpus_id,
        'user_tasks': [task.model_dump(mode='json', exclude_none=True) for task in payload.user_tasks],
        'competency_questions': [
            task.model_dump(mode='json', exclude_none=True)
            for task in payload.user_tasks
            if task.kind == 'competency_question'
        ],
        'strategy': payload.strategy,
        'cq_guided': payload.cq_guided,
        'allowed_extraction_input': codebook.get('allowed_extraction_input', []),
        'held_out_validation_input': codebook.get('held_out_validation_input', []),
    }


def build_funnel_metrics(
    evidence_units: list[EvidenceUnit],
    requirements: list[CandidateRequirement],
    duplicate_groups: list[DuplicateGroup],
) -> dict[str, Any]:
    source_signal_count = sum(len(unit.extracted_facts) for unit in evidence_units)
    supported_ids = {evidence.evidence_unit_id for requirement in requirements for evidence in requirement.source_evidence}
    discarded_domain_content_count = sum(
        1
        for unit in evidence_units
        if unit.id not in supported_ids and exclusion_category_for_evidence(unit) is not None
    )
    return {
        'evidence_unit_count': len(evidence_units),
        'source_signal_count': source_signal_count,
        'candidate_requirement_count': len(requirements),
        'discarded_domain_content_count': discarded_domain_content_count,
        'merged_duplicate_count': sum(max(0, len(group.requirement_ids) - 1) for group in duplicate_groups),
    }


def exclusion_category_for_evidence(unit: EvidenceUnit) -> str | None:
    text = f"{unit.locator or ''} {unit.content} {' '.join(unit.extracted_facts)}".lower()
    if any(token in text for token in ['ifc_class:', 'ifcwall', 'ifcdoor', 'ifcslab', 'pset_']):
        return 'ontology_class_mirroring'
    if any(token in text for token in ['coordinate', 'geometry', 'mesh', 'shape representation']):
        return 'geometry_detail'
    if any(token in text for token in ['sensor value', 'measurement value', 'timeseries value']):
        return 'sensor_measurement_value'
    if any(token in text for token in ['calculation', 'computed load', 'u-value']):
        return 'engineering_calculation'
    if any(token in text for token in ['idshort =', 'modeltype =', 'valuetype =']):
        return 'internal_instance_data'
    return None


def competency_question_coverage(requirements: list[CandidateRequirement], user_tasks: list[UserTask]) -> dict[str, Any]:
    """Coverage of expert user tasks / competency questions by active requirements (RQ1 metric)."""
    active = [requirement for requirement in requirements if requirement.status not in {'rejected', 'merged'}]
    covered = {task_id for requirement in active for task_id in requirement.supports_user_tasks}
    task_ids = [task.id for task in user_tasks]
    return {
        'task_count': len(task_ids),
        'covered_task_count': sum(1 for task_id in task_ids if task_id in covered),
        'uncovered_task_ids': [task_id for task_id in task_ids if task_id not in covered],
        'requirements_without_task_links': [requirement.id for requirement in active if not requirement.supports_user_tasks],
    }


def recommend_reuse(payload: RecommendationRequest) -> RecommendationResponse:
    requirements = list(payload.requirements)
    semantic_candidates = list(payload.semantic_candidates)
    metadata_candidates = list(payload.metadata_candidates)
    if payload.analysis:
        requirements.extend(payload.analysis.requirements)
        semantic_candidates.extend(payload.analysis.semantic_candidates)
        metadata_candidates.extend(payload.analysis.metadata_candidates)

    recommendations: list[ReuseRecommendation] = []
    extension_candidates: list[MetadataCandidate] = []

    for candidate in dedupe_metadata(metadata_candidates):
        term = PROPERTY_CATALOG.get(candidate.property)
        if not term:
            extension_candidates.append(candidate)
            continue
        recommendations.append(recommendation_from_property(candidate.property, candidate_id=candidate.id, confidence=candidate.confidence, reason=f"Matched extracted metadata candidate '{candidate.label}' in {candidate.category}."))

    active_requirements = [requirement for requirement in dedupe_requirements(requirements) if requirement.status not in {'rejected', 'merged'}]
    approved_requirements = [requirement for requirement in active_requirements if requirement.status == 'approved']
    reviewable_requirements = approved_requirements or active_requirements

    for requirement in reviewable_requirements:
        for prop in properties_for_requirement(requirement):
            recommendations.append(
                recommendation_from_property(
                    prop,
                    requirement_id=requirement.id,
                    confidence=requirement.confidence,
                    reason=f"Supports reviewed requirement: '{requirement.normalized_statement or requirement.description or requirement.title}'.",
                )
            )

    for semantic in dedupe_semantic(semantic_candidates):
        lowered = f'{semantic.kind} {semantic.label} {semantic.identifier or ""}'.lower()
        if 'aas' in lowered or 'submodel' in lowered or 'semanticid' in lowered or 'semantic id' in lowered:
            recommendations.append(recommendation_from_property('hasAASSubmodel', candidate_id=semantic.id, confidence=semantic.confidence, reason='Reuse an AAS semantic identifier as a dataset semantic anchor.'))
        if 'ifc' in lowered:
            recommendations.append(recommendation_from_property('hasIFCEntity', candidate_id=semantic.id, confidence=semantic.confidence, reason='Reuse IFC class or schema evidence as a lightweight discovery anchor.'))
        if any(token in lowered for token in ['wall', 'space', 'sensor', 'pump', 'hvac', 'asset', 'element']):
            recommendations.append(recommendation_from_property('describesAssetType', candidate_id=semantic.id, confidence=semantic.confidence, reason='Map asset concepts to a reusable construction asset profile term.'))

    if not recommendations:
        for prop in ['title', 'description', 'keyword', 'distribution', 'semanticAnchor']:
            recommendations.append(recommendation_from_property(prop, reason='Baseline Construct-DCAT discovery profile recommendation.'))

    return RecommendationResponse(recommendations=dedupe_recommendations(recommendations), extension_candidates=extension_candidates)



def generate_constraints(payload: ConstraintGenerationRequest) -> ConstraintGenerationResponse:
    selected = set(payload.selected_recommendation_ids)
    recommendations = [item for item in payload.recommendations if not selected or item.id in selected]
    if not recommendations:
        recommendations = recommend_reuse(RecommendationRequest(analysis=payload.analysis, requirements=payload.requirements)).recommendations

    property_shapes = []
    slots: dict[str, Any] = {}
    slot_names: list[str] = []
    notes: list[str] = ['Review generated SHACL before using it as a normative profile artifact.']

    for rec in recommendations:
        slot_name = slot_name_from_uri(rec.term_uri)
        if slot_name not in slot_names:
            slot_names.append(slot_name)
        term = term_for_uri(rec.term_uri)
        required = rec.priority <= 2 and slot_name in {'title', 'accessURL', 'semanticAnchor'}
        level = 'mandatory' if required else 'recommended' if rec.priority <= 2 else 'optional'
        slots[slot_name] = {
            'title': rec.label,
            'slot_uri': compact_uri(rec.term_uri),
            'range': range_for_term(term, rec.term_uri),
            'required': True if required else None,
            'multivalued': True if slot_name in {'keyword', 'theme', 'distribution', 'semanticAnchor', 'usesOntology', 'hasAASSubmodel', 'hasIFCEntity'} else None,
            'annotations': {
                'term_kind': {'value': 'profile' if rec.action != 'extension' else 'extension'},
                'source_vocabulary': {'value': rec.vocabulary},
                'requirement_level': {'value': level},
                'recommendation_rationale': {'value': rec.rationale},
            },
        }

        severity = 'sh:Violation' if required else 'sh:Warning'
        min_count = '\n        sh:minCount 1 ;' if required else ''
        property_shapes.append(
            f'''    sh:property [
        sh:path {compact_uri(rec.term_uri)} ;{min_count}
        sh:severity {severity} ;
        sh:message "Review {rec.label} for Construct-DCAT discovery metadata." ;
    ] ;'''
        )

    for slot_def in slots.values():
        if slot_def.get('required') is None:
            slot_def.pop('required', None)
        if slot_def.get('multivalued') is None:
            slot_def.pop('multivalued', None)

    shacl = '''@prefix cx: <https://w3id.org/cx#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix sh: <http://www.w3.org/ns/shacl#> .

cx:ConstructionDatasetRequirementShape
    a sh:NodeShape ;
    sh:targetClass dcat:Dataset ;
''' + '\n'.join(property_shapes).rstrip(' ;') + ' .\n'

    profile_draft = {
        'id': 'https://w3id.org/construct-dcat/profile/generated-requirements',
        'name': 'generated_requirement_profile',
        'title': 'Generated Requirement Profile Draft',
        'description': 'Human-reviewed draft generated from requirement extraction and reuse recommendations.',
        'prefixes': {
            'linkml': 'https://w3id.org/linkml/',
            'dcat': 'http://www.w3.org/ns/dcat#',
            'dcterms': 'http://purl.org/dc/terms/',
            'cx': 'https://w3id.org/cx#',
            'skos': 'http://www.w3.org/2004/02/skos/core#',
            'foaf': 'http://xmlns.com/foaf/0.1/',
            'prov': 'http://www.w3.org/ns/prov#',
        },
        'imports': ['linkml:types'],
        'default_prefix': 'cx',
        'default_range': 'string',
        'classes': {
            'GeneratedConstructionDatasetProfile': {
                'title': 'Generated Construction Dataset Profile',
                'is_a': 'DcatDataset',
                'class_uri': 'cx:GeneratedConstructionDatasetProfile',
                'slots': slot_names,
                'annotations': {
                    'term_kind': {'value': 'profile'},
                    'profile_of': {'value': 'dcat:Dataset'},
                    'requirement_level': {'value': 'recommended'},
                },
            }
        },
        'slots': slots,
        'enums': {},
    }

    return ConstraintGenerationResponse(shacl=shacl, profile_draft=profile_draft, validation_notes=notes)



TEXT_EVIDENCE_PATTERNS = {
    'descriptive_metadata': ['title', 'description', 'keyword', 'theme', 'publisher', 'catalog', 'dataset metadata'],
    'semantic_anchor': ['semantic', 'ontology', 'vocabulary', 'concept', 'skos', 'semantic id', 'semanticid', 'aas', 'submodel', 'ifc', 'bot'],
    'asset_semantics': ['asset', 'building element', 'wall', 'space', 'zone', 'equipment', 'sensor', 'hvac', 'pump'],
    'lifecycle_context': ['planning', 'design', 'construction', 'operation', 'maintenance', 'demolition', 'lifecycle', 'life cycle'],
    'technical_metadata': ['format', 'media type', 'schema version', 'version', 'download', 'distribution', 'json', 'rdf', 'ttl', 'ifc file', 'csv'],
    'access_policy': ['license', 'rights', 'access', 'access rights', 'policy', 'permission', 'restricted', 'usage'],
    'quality_provenance': ['provenance', 'quality', 'completeness', 'confidence', 'source system', 'origin'],
}


def extract_evidence_units(payload: AnalysisRequest) -> list[EvidenceUnit]:
    evidence_units: list[EvidenceUnit] = []
    if payload.text and payload.text.strip():
        evidence_units.extend(evidence_from_text('text description', payload.text))

    for artifact in payload.artifacts:
        kind = detect_kind(artifact)
        if kind == 'aasx':
            evidence_units.extend(evidence_from_aasx(artifact.name, artifact))
            continue
        content = decode_artifact_text(artifact)
        if kind == 'aas-json':
            evidence_units.extend(evidence_from_aas_json(artifact.name, content))
        elif kind == 'dcat-rdf':
            evidence_units.extend(evidence_from_dcat_rdf(artifact.name, content))
        elif kind == 'ifc':
            evidence_units.extend(evidence_from_ifc(artifact.name, content))
        else:
            evidence_units.extend(evidence_from_text(artifact.name, content, artifact_kind='text'))
    return dedupe_evidence_units(evidence_units)


def evidence_from_text(source: str, text: str, artifact_kind: str = 'text') -> list[EvidenceUnit]:
    evidence_units: list[EvidenceUnit] = []
    for index, sentence in enumerate(split_sentences(text), start=1):
        lowered = sentence.lower()
        facts: list[str] = []
        for group, tokens in TEXT_EVIDENCE_PATTERNS.items():
            if any(token in lowered for token in tokens):
                facts.append(f'Mentions {human_label(group)} requirement evidence')
        if not facts:
            continue
        evidence_units.append(
            evidence_unit(
                source,
                artifact_kind,
                f'sentence:{index}',
                sentence,
                facts,
                0.72,
            )
        )
    return evidence_units


def evidence_from_aas_json(source: str, content: str) -> list[EvidenceUnit]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return evidence_from_text(source, content)

    evidence_units: list[EvidenceUnit] = []

    def walk(value: Any, path: str = '$') -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_label = str(key)
                key_norm = key_label.lower()
                child_path = f'{path}.{key_label}'
                if key_norm in {'semanticid', 'semanticidlist'}:
                    for identifier in extract_identifiers(child)[:20]:
                        evidence_units.append(
                            evidence_unit(
                                source,
                                'aas-json',
                                child_path,
                                f'semanticId = {identifier}',
                                ['AAS submodel has semantic identifier', 'Potential dataset-level semantic anchor'],
                                0.86,
                            )
                        )
                elif key_norm == 'idshort' and is_scalar(child):
                    facts = ['AAS model contains idShort value']
                    if 'submodel' in path.lower():
                        facts.append('AAS submodel can be referenced by profile metadata')
                    evidence_units.append(evidence_unit(source, 'aas-json', child_path, f'idShort = {child}', facts, 0.8))
                elif key_norm == 'id' and is_scalar(child) and ('submodel' in path.lower() or 'concept' in path.lower()):
                    evidence_units.append(
                        evidence_unit(source, 'aas-json', child_path, f'{key_label} = {child}', ['AAS submodel or concept has stable identifier'], 0.78)
                    )
                elif key_norm in {'preferredname', 'displayname', 'description'}:
                    for label in extract_labels(child)[:20]:
                        evidence_units.append(evidence_unit(source, 'aas-json', child_path, f'{key_label} = {label}', ['AAS concept description contains human-readable label'], 0.74))
                elif key_norm in {'assetkind', 'globalassetid'} and is_scalar(child):
                    evidence_units.append(
                        evidence_unit(source, 'aas-json', child_path, f'{key_label} = {child}', ['AAS asset identity can support asset-level discovery'], 0.82)
                    )
                elif key_norm in {'modeltype', 'valuetype', 'category', 'kind'} and is_scalar(child):
                    evidence_units.append(
                        evidence_unit(source, 'aas-json', child_path, f'{key_label} = {child}', ['AAS technical structure can support representation metadata'], 0.72)
                    )
                walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f'{path}[{index}]')

    walk(data)
    return evidence_units


def evidence_from_aas_xml(source: str, content: str) -> list[EvidenceUnit]:
    evidence_units: list[EvidenceUnit] = []
    for index, value in enumerate(clean_matches(re.findall(r'<(?:[^:>]+:)?idShort[^>]*>(.*?)</(?:[^:>]+:)?idShort>', content, flags=re.IGNORECASE | re.DOTALL))[:80]):
        evidence_units.append(evidence_unit(source, 'aas-xml', f'//idShort[{index}]', f'idShort = {value}', ['AAS model contains idShort value'], 0.78))
    for index, value in enumerate(clean_matches(re.findall(r'(?:https?://|urn:|irdi:|0173-)[^\s<>"\']+', content))[:80]):
        evidence_units.append(evidence_unit(source, 'aas-xml', f'//semanticId[{index}]', f'semantic identifier = {value}', ['AAS XML contains semantic identifier', 'Potential dataset-level semantic anchor'], 0.82))
    for index, value in enumerate(clean_matches(re.findall(r'<(?:[^:>]+:)?preferredName[^>]*>(.*?)</(?:[^:>]+:)?preferredName>', content, flags=re.IGNORECASE | re.DOTALL))[:80]):
        evidence_units.append(evidence_unit(source, 'aas-xml', f'//preferredName[{index}]', f'preferredName = {value}', ['AAS concept description contains human-readable label'], 0.74))
    return evidence_units


def evidence_from_aasx(source: str, artifact: ArtifactPayload) -> list[EvidenceUnit]:
    try:
        raw = decode_artifact_bytes(artifact)
    except ValueError as exc:
        return [evidence_unit(source, 'aasx', 'package', str(exc), ['AASX package could not be decoded'], 0.2)]

    evidence_units = [evidence_unit(source, 'aasx', 'package', f'AASX package {source}', ['AASX package-level source artifact'], 0.7)]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            names = [name for name in package.namelist() if not name.endswith('/')]
            evidence_units[0].extracted_facts.append(f'AASX package contains {len(names)} file entries')
            for name in names:
                lowered = name.lower()
                if not lowered.endswith(('.json', '.xml', '.aas')):
                    continue
                try:
                    text = package.read(name).decode('utf-8', errors='replace')
                except KeyError:
                    continue
                embedded_source = f'{source}:{name}'
                if lowered.endswith(('.json', '.aas')):
                    try:
                        json.loads(text)
                    except json.JSONDecodeError:
                        evidence_units.extend(prefix_evidence_locators(evidence_from_aas_xml(embedded_source, text), f'{source}:{name}:'))
                    else:
                        evidence_units.extend(prefix_evidence_locators(evidence_from_aas_json(embedded_source, text), f'{source}:{name}:'))
                else:
                    evidence_units.extend(prefix_evidence_locators(evidence_from_aas_xml(embedded_source, text), f'{source}:{name}:'))
    except zipfile.BadZipFile:
        text = raw.decode('utf-8', errors='replace')
        evidence_units.extend(evidence_from_aas_json(source, text) or evidence_from_aas_xml(source, text))
    return evidence_units


def evidence_from_ifc(source: str, content: str) -> list[EvidenceUnit]:
    schema_match = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", content, flags=re.IGNORECASE)
    schema = schema_match.group(1) if schema_match else 'IFC'
    classes = Counter(match.upper() for match in re.findall(r'\bIFC[A-Z][A-Z0-9_]*\b', content, flags=re.IGNORECASE))
    psets = Counter(match for match in re.findall(r'\bPset_[A-Za-z0-9_]+', content))
    evidence_units = [
        evidence_unit(source, 'ifc', 'FILE_SCHEMA', f'IFC schema detected: {schema}', ['Dataset should expose schema/conformance information'], 0.82)
    ]
    for name, count in classes.most_common(30):
        evidence_units.append(
            evidence_unit(
                source,
                'ifc',
                f'IFC_CLASS:{name}',
                f'{name} occurs {count} time(s)',
                ['IFC entity can support semantic anchoring', 'IFC entity can support construction asset type discovery'],
                min(0.9, 0.65 + count / 100),
            )
        )
    for name, count in psets.most_common(20):
        evidence_units.append(evidence_unit(source, 'ifc', f'PSET:{name}', f'{name} occurs {count} time(s)', ['IFC property set can support metadata requirement discovery'], 0.7))
    return evidence_units


def evidence_from_dcat_rdf(source: str, content: str) -> list[EvidenceUnit]:
    predicates: Counter[str] = Counter()
    evidence_units: list[EvidenceUnit] = []
    parsed = False
    for fmt in ['turtle', 'json-ld', 'xml', 'nt']:
        graph = Graph()
        try:
            graph.parse(data=content, format=fmt)
        except Exception:
            continue
        for _, predicate, obj in graph:
            predicates[str(predicate)] += 1
            if looks_like_uri(str(obj)) and any(token in str(obj).lower() for token in ['ifc', 'aas', 'bot', 'skos', 'w3id']):
                evidence_units.append(
                    evidence_unit(source, 'dcat-rdf', f'object:{obj}', f'Linked semantic resource: {obj}', ['Existing metadata links to an external semantic resource'], 0.78)
                )
        parsed = True
        break

    if not parsed:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return evidence_from_text(source, content)
        for key in collect_keys(data):
            predicates[key] += 1

    for predicate, count in predicates.most_common(80):
        prop = URI_TO_PROPERTY.get(predicate) or key_to_property(predicate)
        facts = ['Existing metadata uses reusable predicate or key']
        if prop:
            facts.append(f'Existing metadata suggests {prop} profile term')
        evidence_units.append(evidence_unit(source, 'dcat-rdf', f'predicate:{predicate}', f'{predicate} used {count} time(s)', facts, 0.78))
    return evidence_units


def extract_candidate_requirements(evidence_units: list[EvidenceUnit]) -> list[CandidateRequirement]:
    requirements: list[CandidateRequirement] = []

    def matching(*tokens: str) -> list[EvidenceUnit]:
        lowered_tokens = [token.lower() for token in tokens]
        return [unit for unit in evidence_units if any(token in evidence_text(unit).lower() for token in lowered_tokens)]

    add_requirement(requirements, 'semantic_anchor', 'A dcat:Dataset should be able to reference one or more AAS semantic identifiers to support discovery and semantic interpretation.', matching('semanticid', 'semantic identifier'), 'reference AAS semantic identifiers', 'uri', 'recommended', ['F', 'I', 'R'], ['cx:semanticAnchor', 'cx:hasAASSubmodel'])
    add_requirement(requirements, 'semantic_anchor', 'A dcat:Dataset should be able to indicate which AAS submodels are represented or referenced by the dataset.', matching('aas submodel', 'idshort', 'submodel'), 'reference AAS submodels', 'uri', 'recommended', ['F', 'I', 'R'], ['cx:hasAASSubmodel'])
    add_requirement(requirements, 'technical_metadata', 'A dcat:Dataset or dcat:Distribution should expose the IFC schema version or conformance target of the represented file.', matching('ifc schema', 'file_schema'), 'indicate IFC schema version or conformance target', 'uri', 'recommended', ['I', 'R'], ['dcterms:conformsTo', 'dcterms:format', 'dcat:mediaType'], resource_type='Distribution')
    add_requirement(requirements, 'semantic_anchor', 'A dcat:Dataset should be able to reference relevant IFC entity classes as lightweight semantic anchors for discovery.', matching('ifc entity', 'ifc_class', 'ifcwall', 'ifcspace'), 'reference IFC entity classes', 'class_reference', 'recommended', ['F', 'I', 'R'], ['cx:hasIFCEntity'])
    add_requirement(requirements, 'semantic_anchor', 'A dcat:Dataset should indicate the construction asset type or asset category it describes.', matching('construction asset type', 'asset type', 'asset-level', 'wall', 'pump', 'sensor', 'hvac', 'space', 'equipment'), 'indicate construction asset type', 'controlled_concept', 'recommended', ['F', 'R'], ['cx:describesAssetType', 'dcat:theme'])
    add_requirement(requirements, 'lifecycle_context', 'A dcat:Dataset should indicate the construction lifecycle phase to which the data relates.', matching('lifecycle', 'life cycle', 'planning', 'design', 'construction', 'operation', 'maintenance', 'demolition'), 'indicate construction lifecycle phase', 'controlled_concept', 'recommended', ['F', 'R'], ['cx:hasLifecyclePhase', 'dcat:theme'])
    add_requirement(requirements, 'access_policy', 'A dcat:Dataset or dcat:Distribution should describe access conditions, license, rights, or reuse policy.', matching('license', 'rights', 'access', 'policy', 'permission', 'restricted'), 'describe access and reuse conditions', 'uri', 'recommended', ['A', 'R'], ['dcterms:license', 'dcterms:accessRights', 'dcat:accessURL'])
    add_requirement(requirements, 'technical_metadata', 'A dcat:Distribution should expose technical representation metadata such as format, media type, download URL, and schema version.', matching('format', 'media type', 'schema version', 'download', 'distribution', 'json', 'rdf', 'ttl', 'csv'), 'describe distribution format and representation', 'distribution', 'recommended', ['A', 'I', 'R'], ['dcat:distribution', 'dcterms:format', 'dcat:mediaType', 'dcat:downloadURL'])
    add_requirement(requirements, 'descriptive_metadata', 'A dcat:Dataset should provide reusable descriptive metadata such as title, description, keywords, themes, and publisher.', matching('title', 'description', 'keyword', 'theme', 'publisher', 'catalog', 'dataset metadata'), 'provide descriptive dataset metadata', 'literal', 'mandatory', ['F'], ['dcterms:title', 'dcterms:description', 'dcat:keyword', 'dcat:theme', 'dcterms:publisher'])
    add_requirement(requirements, 'quality_provenance', 'A dcat:Dataset should expose provenance, quality, completeness, confidence, or source-system metadata where available.', matching('provenance', 'quality', 'completeness', 'confidence', 'source system', 'origin'), 'describe provenance and quality context', 'literal', 'optional', ['R'], ['dcterms:provenance', 'prov:wasDerivedFrom', 'cx:hasDataSourceSystem'])

    return [requirement for requirement in requirements if requirement.source_evidence]


def add_requirement(requirements: list[CandidateRequirement], requirement_type: str, statement: str, evidence: list[EvidenceUnit], metadata_need: str, value_kind: str, obligation_hint: str, fair_dimensions: list[str], candidate_terms: list[str], resource_type: str = 'Dataset') -> None:
    if not evidence:
        return
    confidence = min(0.92, max(unit.confidence for unit in evidence) + min(len(evidence), 5) * 0.02)
    category = category_for_requirement_type(requirement_type)
    requirements.append(
        CandidateRequirement(
            id=stable_id('req', requirement_type, metadata_need, *(unit.id for unit in evidence[:6])),
            raw_statement='; '.join(unit.content for unit in evidence[:3]),
            normalized_statement=statement,
            requirement_type=requirement_type,
            source_evidence=[source_evidence(unit) for unit in evidence[:8]],
            normalized_intent=NormalizedIntent(resource_type=resource_type, metadata_need=metadata_need, value_kind=value_kind, obligation_hint=obligation_hint),
            fair_dimensions=fair_dimensions,
            fair_rationale=fair_rationale_for(requirement_type, fair_dimensions),
            candidate_metadata_actions=[
                CandidateMetadataAction(
                    action='reuse_existing_term' if any(term.startswith(('dcat:', 'dcterms:', 'prov:')) for term in candidate_terms) else 'create_extension',
                    target_class=resource_type,
                    candidate_terms=candidate_terms,
                    rationale=metadata_action_rationale(metadata_need, candidate_terms),
                )
            ],
            title=title_for_statement(statement),
            description=statement,
            category=category,
            source=', '.join(sorted({unit.artifact_name for unit in evidence}))[:120],
            evidence=[unit.content for unit in evidence[:8]],
            confidence=confidence,
        )
    )


def normalize_requirements(requirements: list[CandidateRequirement]) -> list[CandidateRequirement]:
    for requirement in requirements:
        if not requirement.normalized_statement:
            requirement.normalized_statement = requirement.description or requirement.raw_statement or requirement.title
        if not requirement.raw_statement:
            requirement.raw_statement = requirement.description or requirement.normalized_statement
        requirement.title = requirement.title or title_for_statement(requirement.normalized_statement or requirement.id)
        requirement.description = requirement.description or requirement.normalized_statement or requirement.raw_statement or requirement.title
        requirement.category = requirement.category or category_for_requirement_type(requirement.requirement_type)
    return requirements


def classify_requirements(requirements: list[CandidateRequirement]) -> list[CandidateRequirement]:
    for requirement in requirements:
        if requirement.requirement_type == 'unknown':
            requirement.requirement_type = requirement_type_for_category(requirement.category or infer_category(requirement.normalized_statement or ''))
        requirement.category = category_for_requirement_type(requirement.requirement_type)
    return requirements


def assign_fair_dimensions(requirements: list[CandidateRequirement]) -> list[CandidateRequirement]:
    for requirement in requirements:
        if not requirement.fair_dimensions:
            requirement.fair_dimensions = default_fair_dimensions(requirement.requirement_type)
        if not requirement.fair_rationale:
            requirement.fair_rationale = fair_rationale_for(requirement.requirement_type, requirement.fair_dimensions)
    return requirements


def suggest_candidate_metadata_actions(requirements: list[CandidateRequirement]) -> list[CandidateRequirement]:
    for requirement in requirements:
        if requirement.candidate_metadata_actions:
            continue
        terms = terms_for_requirement(requirement)
        requirement.candidate_metadata_actions = [
            CandidateMetadataAction(
                action='reuse_existing_term' if any(term.startswith(('dcat:', 'dcterms:', 'prov:')) for term in terms) else 'create_extension',
                target_class=requirement.normalized_intent.resource_type,
                candidate_terms=terms,
                rationale=metadata_action_rationale(requirement.normalized_intent.metadata_need, terms),
            )
        ]
    return requirements


def validate_requirements(requirements: list[CandidateRequirement]) -> list[CandidateRequirement]:
    for requirement in requirements:
        validate_requirement(requirement)
    return requirements


def validate_requirement(requirement: CandidateRequirement) -> CandidateRequirement:
    requirement.requirement_scope = requirement.requirement_scope if requirement.requirement_scope != 'unknown' else infer_requirement_scope(requirement)

    if not requirement.source_evidence:
        requirement.validation_status = 'missing_evidence'
        requirement.confidence = min(requirement.confidence, 0.4)
        return requirement

    validation_status = 'valid'
    for action in requirement.candidate_metadata_actions:
        terms = clean_matches(action.candidate_terms)
        action.candidate_terms = terms
        if action.action in {'reuse_existing_term', 'specialize_existing_term'}:
            for term in terms:
                if term not in term_catalog():
                    validation_status = stronger_validation_status(validation_status, 'unknown_term')
                    requirement.confidence = min(requirement.confidence, 0.55)
                    continue
                if not term_matches_resource(term, action.target_class or requirement.normalized_intent.resource_type):
                    validation_status = stronger_validation_status(validation_status, 'resource_mismatch')
                    requirement.confidence = min(requirement.confidence, 0.6)
        elif action.action == 'create_extension':
            if not terms or any(not term.startswith('cx:') for term in terms):
                validation_status = stronger_validation_status(validation_status, 'needs_review')
                requirement.confidence = min(requirement.confidence, 0.6)

    requirement.validation_status = validation_status
    populate_action_hints(requirement)
    return requirement


def populate_action_hints(requirement: CandidateRequirement) -> CandidateRequirement:
    """Fill the RQ1 -> RQ2 handoff fields on metadata actions.

    ``constraint_hint`` is derived from the normalized intent unless the
    extractor or reviewer supplied one; ``source_requirement_id`` backlinks the
    action to its requirement for ProfileChangeSet provenance.
    """
    from .models import ConstraintHint

    for action in requirement.candidate_metadata_actions:
        if action.constraint_hint is None:
            action.constraint_hint = ConstraintHint(
                value_kind=requirement.normalized_intent.value_kind,
                obligation=requirement.normalized_intent.obligation_hint,
            )
        if action.source_requirement_id is None:
            action.source_requirement_id = requirement.id
    return requirement


def stronger_validation_status(current: str, candidate: str) -> str:
    priority = {
        'valid': 0,
        'needs_review': 1,
        'resource_mismatch': 2,
        'unknown_term': 3,
        'invalid_schema': 4,
        'missing_evidence': 5,
    }
    return candidate if priority.get(candidate, 0) > priority.get(current, 0) else current


def infer_requirement_scope(requirement: CandidateRequirement) -> str:
    actions = {action.action for action in requirement.candidate_metadata_actions}
    if 'add_constraint' in actions or requirement.requirement_type == 'validation_constraint':
        return 'validation_constraint'
    if 'add_usage_note' in actions:
        return 'documentation_guidance'
    if requirement.requirement_type == 'controlled_vocabulary' or requirement.normalized_intent.value_kind == 'controlled_concept':
        return 'controlled_vocabulary'
    if requirement.requirement_type == 'competency_question':
        return 'example_requirement'
    if requirement.normalized_intent.obligation_hint in {'mandatory', 'recommended', 'optional'} and not requirement.candidate_metadata_actions:
        return 'obligation_level'
    if requirement.candidate_metadata_actions:
        return 'profile_element'
    return 'unknown'


def term_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for term, info in RQ2_TERMS.items():
        if info.get('type') == 'property':
            catalog[term] = {
                'resource_types': info.get('domain'),
                'range': info.get('range'),
                'source': 'rq2_term_registry',
            }
        elif info.get('type') == 'class':
            resource_type = normalize_registry_resource(term) or term.rsplit(':', 1)[-1]
            catalog[term] = {
                'resource_types': [resource_type],
                'source': 'rq2_term_registry',
            }
    for term in PROPERTY_CATALOG.values():
        compact = compact_registry_uri(term['uri'])
        existing = catalog.get(compact, {})
        catalog[compact] = {**existing, **term, 'resource_types': existing.get('resource_types')}
    return catalog


def term_matches_resource(term: str, resource_type: str | None) -> bool:
    if not resource_type or resource_type == 'Unknown':
        return True
    if term not in term_catalog():
        return True
    return rq2_domain_compatible(term, resource_type)


def detect_duplicate_requirements(requirements: list[CandidateRequirement]) -> list[DuplicateGroup]:
    groups: list[DuplicateGroup] = []
    seen: set[str] = set()
    active = [item for item in requirements if item.status not in {'rejected', 'merged'}]
    for index, left in enumerate(active):
        if left.id in seen:
            continue
        related = [left]
        for right in active[index + 1:]:
            if right.id in seen:
                continue
            same_type = left.requirement_type == right.requirement_type
            same_resource = left.normalized_intent.resource_type == right.normalized_intent.resource_type
            similarity = token_jaccard(left.normalized_intent.metadata_need, right.normalized_intent.metadata_need)
            threshold = 0.55 if same_type and same_resource else 0.7
            if similarity >= threshold:
                related.append(right)
        if len(related) > 1:
            for item in related:
                seen.add(item.id)
            statement = merged_statement_for(related)
            groups.append(
                DuplicateGroup(
                    id=stable_id('dup', *(item.id for item in related)),
                    requirement_ids=[item.id for item in related],
                    suggested_merged_statement=statement,
                    reason='Requirements share type, resource target, and overlapping normalized metadata needs.',
                    confidence=min(0.9, 0.62 + 0.06 * len(related)),
                )
            )
    return groups


def upgrade_legacy_requirement(requirement: CandidateRequirement) -> CandidateRequirement:
    if requirement.source_evidence:
        return requirement
    statement = requirement.description or requirement.normalized_statement or requirement.title or 'Extracted metadata requirement.'
    req_type = requirement_type_for_category(requirement.category or infer_category(statement))
    source = requirement.source or 'analysis'
    unit = evidence_unit(
        source,
        'unknown',
        None,
        '; '.join(requirement.evidence) or statement,
        [f'Legacy analyzer suggested {requirement.category or category_for_requirement_type(req_type)}'],
        requirement.confidence,
    )
    upgraded = requirement.model_copy(deep=True)
    upgraded.raw_statement = upgraded.raw_statement or statement
    upgraded.normalized_statement = upgraded.normalized_statement or statement
    upgraded.requirement_type = req_type
    upgraded.source_evidence = [source_evidence(unit)]
    upgraded.normalized_intent = NormalizedIntent(
        resource_type='Dataset',
        metadata_need=metadata_need_for_requirement(req_type, statement),
        value_kind=value_kind_for_requirement(req_type),
        obligation_hint='recommended',
    )
    upgraded.fair_dimensions = upgraded.fair_dimensions or default_fair_dimensions(req_type)
    upgraded.fair_rationale = upgraded.fair_rationale or fair_rationale_for(req_type, upgraded.fair_dimensions)
    upgraded.candidate_metadata_actions = upgraded.candidate_metadata_actions or [
        CandidateMetadataAction(
            action='reuse_existing_term',
            target_class='Dataset',
            candidate_terms=terms_for_requirement(upgraded),
            rationale='Legacy analyzer output was normalized into a reviewable requirement record.',
        )
    ]
    upgraded.category = category_for_requirement_type(req_type)
    upgraded.title = upgraded.title or title_for_statement(statement)
    upgraded.description = upgraded.description or statement
    upgraded.source = source
    upgraded.evidence = upgraded.evidence or [unit.content]
    return upgraded


def analyze_artifact(artifact: ArtifactPayload):
    kind = detect_kind(artifact)
    if kind == 'aasx':
        return analyze_aasx(artifact.name, artifact)

    content = decode_artifact_text(artifact)
    if kind == 'aas-json':
        return analyze_aas_json(artifact.name, content)
    if kind == 'dcat-rdf':
        return analyze_dcat_metadata(artifact.name, content)
    if kind == 'ifc':
        return analyze_ifc(artifact.name, content)
    return analyze_text(artifact.name, content)



def analyze_aasx(source: str, artifact: ArtifactPayload):
    try:
        raw = decode_artifact_bytes(artifact)
    except ValueError as exc:
        summary = ArtifactSummary(name=source, kind='aasx', evidence_count=0, notes=[str(exc)])
        return summary, [], [], [], [], []

    requirements: list[CandidateRequirement] = []
    semantic_candidates: list[SemanticCandidate] = []
    metadata_candidates: list[MetadataCandidate] = []
    questions: list[CompetencyQuestion] = []
    extracted_attributes: list[ExtractedAttribute] = []
    notes: list[str] = []
    embedded_count = 0

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            names = [name for name in package.namelist() if not name.endswith('/')]
            notes.append(f'{len(names)} package entries')

            for name in names:
                lowered = name.lower()
                if not lowered.endswith(('.json', '.xml', '.aas')):
                    continue

                try:
                    payload = package.read(name)
                except KeyError:
                    continue
                text = payload.decode('utf-8', errors='replace')

                if lowered.endswith(('.json', '.aas')):
                    try:
                        json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    summary, reqs, sem, meta, qs, attrs = analyze_aas_json(f'{source}:{name}', text)
                    if summary.evidence_count:
                        embedded_count += 1
                        requirements.extend(reqs)
                        semantic_candidates.extend(sem)
                        metadata_candidates.extend(meta)
                        questions.extend(qs)
                        extracted_attributes.extend(attrs)
                    continue

                summary, reqs, sem, meta, qs, attrs = analyze_aas_xml(f'{source}:{name}', text)
                if summary.evidence_count:
                    embedded_count += 1
                    requirements.extend(reqs)
                    semantic_candidates.extend(sem)
                    metadata_candidates.extend(meta)
                    questions.extend(qs)
                    extracted_attributes.extend(attrs)
    except zipfile.BadZipFile:
        fallback = decode_artifact_text(artifact)
        summary, reqs, sem, meta, qs, attrs = analyze_text(source, fallback)
        summary.kind = 'aasx'
        summary.notes.append('AASX package could not be opened as ZIP; scanned decoded text fallback.')
        return summary, reqs, sem, meta, qs, attrs

    if embedded_count:
        notes.append(f'{embedded_count} embedded AAS payload(s) analyzed')
    else:
        notes.append('No parseable embedded AAS JSON/XML payload found')

    summary = ArtifactSummary(
        name=source,
        kind='aasx',
        evidence_count=sum(len(item.evidence) for item in semantic_candidates),
        notes=notes,
    )
    return summary, requirements, semantic_candidates, metadata_candidates, questions, dedupe_attributes(extracted_attributes)


def analyze_aas_xml(source: str, content: str):
    idshorts = clean_matches(re.findall(r'<(?:[A-Za-z0-9_]+:)?idShort[^>]*>\s*([^<]+)', content, flags=re.IGNORECASE))
    identifiers = clean_matches(
        re.findall(r'(?:https?://[^\s<>"\']+|urn:[^\s<>"\']+|irdi:[^\s<>"\']+|0173-[^\s<>"\']+)', content)
    )
    concept_labels = clean_matches(
        re.findall(r'<(?:[A-Za-z0-9_]+:)?preferredName[^>]*>\s*([^<]+)', content, flags=re.IGNORECASE)
    )

    if not idshorts and not identifiers and not concept_labels and 'submodel' not in content.lower():
        return ArtifactSummary(name=source, kind='aas-xml', evidence_count=0, notes=[]), [], [], [], [], []

    requirements = [
        CandidateRequirement(
            id=stable_id('req', source, 'aas-xml-semantic-anchors'),
            title='Reuse AAS package identifiers as metadata anchors',
            description='AASX packages can contribute submodels, idShort values, concept descriptions, and semantic identifiers as discovery-level anchors.',
            category='Semantic Anchors',
            source=source,
            evidence=['AAS XML payload detected in AASX package'],
            confidence=0.82,
        )
    ]
    metadata_candidates = [
        metadata_candidate('semanticAnchor', 'Semantic Anchors', source, 'AASX package payload detected', 0.82),
        metadata_candidate('hasAASSubmodel', 'Semantic Anchors', source, 'AASX package payload detected', 0.8),
        metadata_candidate('hasDataSourceSystem', 'Quality Metadata', source, 'AASX package source', 0.64),
    ]

    semantic_candidates: list[SemanticCandidate] = []
    extracted_attributes: list[ExtractedAttribute] = []
    for index, value in enumerate(idshorts[:80]):
        extracted_attributes.append(extracted_attribute(source, f'//idShort[{index}]', 'idShort', value, 'AAS Attribute', 0.82))
    for index, value in enumerate(identifiers[:80]):
        extracted_attributes.append(extracted_attribute(source, f'//semanticId[{index}]', 'semanticId', value, 'Semantic Anchor', 0.82))
    for index, value in enumerate(concept_labels[:80]):
        extracted_attributes.append(extracted_attribute(source, f'//preferredName[{index}]', 'preferredName', value, 'AAS Attribute', 0.78))

    for label, kind in (
        [(item, 'xml-idShort') for item in idshorts[:40]]
        + [(item, 'semantic-id') for item in identifiers[:40]]
        + [(item, 'concept-description') for item in concept_labels[:40]]
    ):
        semantic_candidates.append(
            SemanticCandidate(
                id=stable_id('sem', source, kind, label),
                label=label,
                kind=f'aas-{kind}',
                identifier=label if looks_like_uri(label) else None,
                source=source,
                evidence=[kind],
                confidence=0.78,
            )
        )

    notes = [f'{len(idshorts)} idShort values', f'{len(identifiers)} semantic identifiers', f'{len(concept_labels)} concept labels']
    questions = [generated_question('Semantic Anchors', source), generated_question('Dataset Metadata', source)]
    return ArtifactSummary(name=source, kind='aas-xml', evidence_count=len(semantic_candidates), notes=notes), requirements, semantic_candidates, metadata_candidates, questions, dedupe_attributes(extracted_attributes)


def analyze_text(source: str, text: str):
    requirements: list[CandidateRequirement] = []
    semantic_candidates: list[SemanticCandidate] = []
    metadata_candidates: list[MetadataCandidate] = []
    questions: list[CompetencyQuestion] = []
    evidence_count = 0

    sentences = split_sentences(text)
    for sentence in sentences:
        lowered = sentence.lower()
        for rule in TEXT_RULES:
            if any(token in lowered for token in rule['tokens']):
                evidence_count += 1
                req_id = stable_id('req', rule['category'], rule['title'], source)
                requirements.append(CandidateRequirement(id=req_id, title=rule['title'], description=rule['description'], category=rule['category'], source=source, evidence=[sentence], confidence=0.7))
                for prop in rule['properties']:
                    metadata_candidates.append(metadata_candidate(prop, rule['category'], source, sentence, 0.72))
        if sentence.endswith('?'):
            questions.append(CompetencyQuestion(id=stable_id('cq', source, sentence), question=sentence, category=infer_category(sentence), source=source, evidence=sentence))

    for concept in re.findall(r'\b(?:IFC[A-Z][A-Za-z0-9]+|AAS|BOT|HVAC|BIM|wall|pump|sensor|submodel|semantic ID)\b', text, flags=re.IGNORECASE):
        semantic_candidates.append(SemanticCandidate(id=stable_id('sem', source, concept), label=concept, kind='domain-concept', source=source, evidence=[concept], confidence=0.68))

    for category in sorted({item.category for item in requirements}):
        questions.append(generated_question(category, source))

    return ArtifactSummary(name=source, kind='text', evidence_count=evidence_count, notes=['Text requirements scanned with rule-based discovery heuristics.']), requirements, semantic_candidates, metadata_candidates, questions, []


def analyze_aas_json(source: str, content: str):
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return analyze_text(source, content)

    requirements = [
        CandidateRequirement(
            id=stable_id('req', source, 'aas-semantic-anchors'),
            title='Reuse AAS semantic identifiers as metadata anchors',
            description='AAS submodels, semantic IDs, concept descriptions, and idShort values can support discovery-level semantic anchoring.',
            category='Semantic Anchors',
            source=source,
            evidence=['AAS JSON structure detected'],
            confidence=0.88,
        )
    ]
    semantic_candidates: list[SemanticCandidate] = []
    metadata_candidates = [
        metadata_candidate('semanticAnchor', 'Semantic Anchors', source, 'AAS JSON structure detected', 0.86),
        metadata_candidate('hasAASSubmodel', 'Semantic Anchors', source, 'AAS JSON structure detected', 0.84),
        metadata_candidate('hasDataSourceSystem', 'Quality Metadata', source, 'AAS JSON source system', 0.66),
    ]

    idshorts: list[str] = []
    identifiers: list[str] = []
    concept_labels: list[str] = []
    extracted_attributes: list[ExtractedAttribute] = []

    def walk(value: Any, path: str = '$') -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_label = str(key)
                key_norm = key_label.lower()
                child_path = f'{path}.{key_label}'
                if key_norm in AAS_ATTRIBUTE_KEYS:
                    if key_norm in {'semanticid', 'semanticidlist'}:
                        extracted = extract_identifiers(child)
                        identifiers.extend(extracted)
                        for index, identifier in enumerate(extracted[:20]):
                            extracted_attributes.append(extracted_attribute(source, f'{child_path}[{index}]', key_label, identifier, 'Semantic Anchor', 0.86))
                    elif key_norm in {'preferredname', 'displayname', 'description', 'modeltype'}:
                        labels = extract_labels(child)
                        if key_norm == 'preferredname':
                            concept_labels.extend(labels)
                        for index, label in enumerate(labels[:20]):
                            extracted_attributes.append(extracted_attribute(source, f'{child_path}[{index}]', key_label, label, 'AAS Attribute', 0.78))
                    elif is_scalar(child):
                        if key_norm == 'idshort':
                            idshorts.append(str(child))
                        if key_norm == 'id' and ('submodel' in path.lower() or 'concept' in path.lower()):
                            identifiers.append(str(child))
                        extracted_attributes.append(extracted_attribute(source, child_path, key_label, child, 'AAS Attribute', 0.78))
                walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f'{path}[{index}]')

    walk(data)

    for label, kind in [(item, 'idShort') for item in idshorts[:40]] + [(item, 'semantic-id') for item in identifiers[:40]] + [(item, 'concept-description') for item in concept_labels[:40]]:
        semantic_candidates.append(SemanticCandidate(id=stable_id('sem', source, kind, label), label=label, kind=f'aas-{kind}', identifier=label if looks_like_uri(label) else None, source=source, evidence=[kind], confidence=0.82))

    notes = [f'{len(idshorts)} idShort values', f'{len(identifiers)} semantic identifiers', f'{len(concept_labels)} concept labels']
    questions = [generated_question('Semantic Anchors', source), generated_question('Dataset Metadata', source)]
    return ArtifactSummary(name=source, kind='aas-json', evidence_count=len(idshorts) + len(identifiers) + len(concept_labels), notes=notes), requirements, semantic_candidates, metadata_candidates, questions, dedupe_attributes(extracted_attributes)


def analyze_dcat_metadata(source: str, content: str):
    requirements: list[CandidateRequirement] = []
    semantic_candidates: list[SemanticCandidate] = []
    metadata_candidates: list[MetadataCandidate] = []
    questions: list[CompetencyQuestion] = []
    predicates: Counter[str] = Counter()
    extracted_attributes: list[ExtractedAttribute] = []

    parsed = False
    for fmt in ['turtle', 'json-ld', 'xml', 'nt']:
        graph = Graph()
        try:
            graph.parse(data=content, format=fmt)
        except Exception:
            continue
        for subject, predicate, obj in graph:
            predicates[str(predicate)] += 1
            extracted_attributes.append(extracted_attribute(source, str(predicate), str(predicate).rsplit('/', 1)[-1].rsplit('#', 1)[-1], str(obj), 'RDF Metadata', 0.76))
            if looks_like_uri(str(obj)) and any(token in str(obj).lower() for token in ['ifc', 'aas', 'bot', 'skos', 'w3id']):
                semantic_candidates.append(SemanticCandidate(id=stable_id('sem', source, str(obj)), label=str(obj).rsplit('/', 1)[-1], kind='linked-resource', identifier=str(obj), source=source, evidence=[str(predicate)], confidence=0.78))
        parsed = True
        break

    if not parsed:
        try:
            data = json.loads(content)
            for key in collect_keys(data):
                predicates[key] += 1
            extracted_attributes.extend(collect_json_attributes(source, data, '$', limit=160))
        except json.JSONDecodeError:
            return analyze_text(source, content)

    for predicate, count in predicates.most_common():
        prop = URI_TO_PROPERTY.get(predicate) or key_to_property(predicate)
        if prop:
            metadata_candidates.append(metadata_candidate(prop, 'Dataset Metadata' if prop in {'title', 'description', 'keyword', 'theme', 'publisher'} else 'Technical Metadata', source, f'{predicate} used {count} time(s)', 0.8))

    if metadata_candidates:
        requirements.append(CandidateRequirement(id=stable_id('req', source, 'reuse-existing-dcat-patterns'), title='Reuse existing DCAT metadata patterns', description='Existing metadata examples contain properties that can seed a reusable profile.', category='Dataset Metadata', source=source, evidence=[item.label for item in metadata_candidates[:6]], confidence=0.82))
    questions.append(generated_question('Dataset Metadata', source))
    return ArtifactSummary(name=source, kind='dcat-rdf', evidence_count=sum(predicates.values()), notes=[f'{len(predicates)} unique metadata predicates or keys']), requirements, semantic_candidates, metadata_candidates, questions, dedupe_attributes(extracted_attributes)


def analyze_ifc(source: str, content: str):
    schema_match = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", content, flags=re.IGNORECASE)
    schema = schema_match.group(1) if schema_match else 'IFC'
    classes = Counter(match.upper() for match in re.findall(r'\bIFC[A-Z][A-Z0-9_]*\b', content, flags=re.IGNORECASE))
    psets = Counter(match for match in re.findall(r'\bPset_[A-Za-z0-9_]+', content))

    requirements = [
        CandidateRequirement(id=stable_id('req', source, 'ifc-discovery'), title='Expose lightweight IFC discovery metadata', description='IFC artifacts should contribute schema version, entity class, and property set statistics as metadata requirements.', category='Technical Metadata', source=source, evidence=[schema], confidence=0.8),
        CandidateRequirement(id=stable_id('req', source, 'ifc-anchors'), title='Use IFC classes as semantic anchors', description='Frequent IFC classes can be reused as discovery-level semantic anchors without transforming the full model.', category='Semantic Anchors', source=source, evidence=[name for name, _ in classes.most_common(8)], confidence=0.78),
    ]
    metadata_candidates = [
        metadata_candidate('schemaVersion', 'Technical Metadata', source, schema, 0.8),
        metadata_candidate('hasIFCEntity', 'Semantic Anchors', source, ', '.join(name for name, _ in classes.most_common(5)), 0.78),
        metadata_candidate('describesAssetType', 'Asset Semantics', source, ', '.join(name for name, _ in classes.most_common(5)), 0.7),
    ]
    semantic_candidates = [
        SemanticCandidate(id=stable_id('sem', source, name), label=name, kind='ifc-class', identifier=f'https://standards.buildingsmart.org/IFC/DEV/IFC4/ADD2_TC1/OWL#{name.title()}', source=source, evidence=[f'{count} occurrence(s)'], confidence=min(0.9, 0.65 + count / 100))
        for name, count in classes.most_common(30)
    ]
    extracted_attributes = [extracted_attribute(source, 'FILE_SCHEMA', 'FILE_SCHEMA', schema, 'IFC Metadata', 0.82)]
    extracted_attributes.extend(extracted_attribute(source, f'IFC_CLASS[{name}]', name, str(count), 'IFC Class Count', min(0.9, 0.65 + count / 100), 'count') for name, count in classes.most_common(80))
    extracted_attributes.extend(extracted_attribute(source, f'PSET[{name}]', name, str(count), 'IFC Property Set Count', 0.7, 'count') for name, count in psets.most_common(80))
    questions = [generated_question('Semantic Anchors', source), generated_question('Technical Metadata', source)]
    notes = [f'Schema: {schema}', f'{len(classes)} IFC classes', f'{len(psets)} property set references']
    return ArtifactSummary(name=source, kind='ifc', evidence_count=sum(classes.values()) + sum(psets.values()), notes=notes), requirements, semantic_candidates, metadata_candidates, questions, dedupe_attributes(extracted_attributes)


def detect_kind(artifact: ArtifactPayload) -> str:
    name = artifact.name.lower()
    media = (artifact.media_type or '').lower()
    if name.endswith('.aasx') or media in {'application/asset-administration-shell-package', 'application/aasx'}:
        return 'aasx'

    content = decode_artifact_text(artifact).lstrip()[:600].lower()
    if name.endswith(('.ifc', '.ifcspf')) or 'iso-10303-21' in content or 'file_schema' in content:
        return 'ifc'
    if name.endswith(('.ttl', '.rdf', '.owl', '.jsonld', '.nt')) or '@prefix' in content or 'dcat:' in content or 'http://www.w3.org/ns/dcat' in content:
        return 'dcat-rdf'
    if name.endswith('.json') or 'json' in media:
        try:
            data = json.loads(decode_artifact_text(artifact))
        except json.JSONDecodeError:
            return 'text'
        keys = {key.lower() for key in collect_keys(data)}
        if {'submodels', 'semanticid', 'conceptdescriptions', 'idshort'} & keys:
            return 'aas-json'
        if any('dcat' in key or '@type' == key for key in keys):
            return 'dcat-rdf'
    return 'text'



def decode_artifact_bytes(artifact: ArtifactPayload) -> bytes:
    if artifact.content_encoding == 'base64':
        try:
            return base64.b64decode(artifact.content, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f'Artifact {artifact.name} is not valid base64 content') from exc
    return artifact.content.encode('utf-8', errors='replace')


def decode_artifact_text(artifact: ArtifactPayload) -> str:
    if artifact.content_encoding == 'base64':
        try:
            return decode_artifact_bytes(artifact).decode('utf-8', errors='replace')
        except ValueError:
            return ''
    return artifact.content or ''


def clean_matches(values: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        item = re.sub(r'\s+', ' ', value).strip()
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned



def extracted_attribute(source: str, path: str, label: str, value: Any, category: str, confidence: float = 0.7, value_type: str = 'string') -> ExtractedAttribute:
    text = attribute_value(value)
    return ExtractedAttribute(
        id=stable_id('attr', source, path, label, text),
        source=source,
        path=path,
        label=label,
        value=text,
        category=category,
        value_type=value_type,
        confidence=confidence,
    )


def collect_json_attributes(source: str, value: Any, path: str = '$', limit: int = 120) -> list[ExtractedAttribute]:
    attributes: list[ExtractedAttribute] = []

    def walk(current: Any, current_path: str) -> None:
        if len(attributes) >= limit:
            return
        if isinstance(current, dict):
            for key, child in current.items():
                child_path = f'{current_path}.{key}'
                if is_scalar(child):
                    attributes.append(extracted_attribute(source, child_path, str(key), child, 'JSON Metadata', 0.68))
                else:
                    walk(child, child_path)
        elif isinstance(current, list):
            for index, child in enumerate(current):
                walk(child, f'{current_path}[{index}]')

    walk(value, path)
    return attributes


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def attribute_value(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (str, int, float, bool)):
        text = str(value)
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:500]


def metadata_candidate(prop: str, category: str, source: str, evidence: str, confidence: float) -> MetadataCandidate:
    term = PROPERTY_CATALOG.get(prop, {'label': prop, 'range': 'string', 'level': 'recommended'})
    return MetadataCandidate(id=stable_id('meta', source, prop, category), property=prop, label=term['label'], category=category, range=term.get('range', 'string'), requirement_level=term.get('level', 'recommended'), source=source, evidence=[evidence], confidence=confidence)


def recommendation_from_property(prop: str, requirement_id: str | None = None, candidate_id: str | None = None, confidence: float = 0.65, reason: str = '') -> ReuseRecommendation:
    term = PROPERTY_CATALOG[prop]
    action = 'reuse' if term['priority'] == 1 else 'profile' if term['priority'] <= 3 else 'extension'
    return ReuseRecommendation(id=stable_id('rec', prop, requirement_id or '', candidate_id or ''), label=term['label'], vocabulary=term['vocabulary'], term_uri=term['uri'], priority=term['priority'], action=action, requirement_id=requirement_id, candidate_id=candidate_id, rationale=reason or f"Reuse {term['label']} from {term['vocabulary']}.", confidence=confidence)


def properties_for_category(category: str) -> list[str]:
    return {
        'Dataset Metadata': ['title', 'description', 'keyword', 'theme'],
        'Semantic Anchors': ['semanticAnchor', 'usesOntology'],
        'Asset Semantics': ['describesAssetType'],
        'Lifecycle Information': ['hasLifecyclePhase'],
        'Technical Metadata': ['distribution', 'format', 'mediaType', 'schemaVersion'],
        'Access/Policy': ['license', 'accessRights', 'accessURL'],
        'Quality Metadata': ['provenance', 'hasDataSourceSystem'],
    }.get(category, ['description'])



def evidence_unit(source: str, artifact_kind: str, locator: str | None, content: str, facts: list[str], confidence: float) -> EvidenceUnit:
    return EvidenceUnit(
        id=stable_id('ev', source, artifact_kind, locator or '', content),
        source_id=stable_id('source', source),
        artifact_name=source,
        artifact_kind=artifact_kind if artifact_kind in {'text', 'ifc', 'aas-json', 'aas-xml', 'aasx', 'dcat-rdf', 'profile-spec', 'use-case'} else 'unknown',
        locator=locator,
        content=attribute_value(content),
        extracted_facts=clean_matches(facts),
        confidence=confidence,
    )


def source_evidence(unit: EvidenceUnit) -> SourceEvidence:
    return SourceEvidence(
        evidence_unit_id=unit.id,
        source_id=unit.source_id,
        artifact_name=unit.artifact_name,
        artifact_kind=unit.artifact_kind,
        locator=unit.locator,
        evidence_text=unit.content,
        extracted_facts=unit.extracted_facts,
    )


def prefix_evidence_locators(units: list[EvidenceUnit], prefix: str) -> list[EvidenceUnit]:
    for unit in units:
        if unit.locator:
            unit.locator = f'{prefix}{unit.locator}'
    return units


def evidence_text(unit: EvidenceUnit) -> str:
    return f'{unit.artifact_kind} {unit.locator or ""} {unit.content} {" ".join(unit.extracted_facts)}'


def human_label(value: str) -> str:
    return value.replace('_', ' ')


def title_for_statement(statement: str) -> str:
    cleaned = re.sub(r'\s+', ' ', statement).strip()
    return cleaned[:92] + ('...' if len(cleaned) > 92 else '')


def category_for_requirement_type(requirement_type: str) -> str:
    return {
        'descriptive_metadata': 'Dataset Metadata',
        'semantic_anchor': 'Semantic Anchors',
        'technical_metadata': 'Technical Metadata',
        'access_policy': 'Access/Policy',
        'quality_provenance': 'Quality Metadata',
        'lifecycle_context': 'Lifecycle Information',
        'controlled_vocabulary': 'Semantic Anchors',
        'validation_constraint': 'Technical Metadata',
        'competency_question': 'Dataset Metadata',
    }.get(requirement_type, 'Dataset Metadata')


def requirement_type_for_category(category: str) -> str:
    return {
        'Dataset Metadata': 'descriptive_metadata',
        'Semantic Anchors': 'semantic_anchor',
        'Asset Semantics': 'semantic_anchor',
        'Lifecycle Information': 'lifecycle_context',
        'Technical Metadata': 'technical_metadata',
        'Access/Policy': 'access_policy',
        'Quality Metadata': 'quality_provenance',
    }.get(category, 'unknown')


def default_fair_dimensions(requirement_type: str) -> list[str]:
    return {
        'descriptive_metadata': ['F'],
        'semantic_anchor': ['F', 'I', 'R'],
        'technical_metadata': ['I', 'R'],
        'access_policy': ['A', 'R'],
        'quality_provenance': ['R'],
        'lifecycle_context': ['F', 'R'],
        'controlled_vocabulary': ['F', 'I', 'R'],
        'validation_constraint': ['I', 'R'],
    }.get(requirement_type, ['F'])


def fair_rationale_for(requirement_type: str, dimensions: list[str]) -> str:
    labels = ', '.join(dimensions)
    return {
        'descriptive_metadata': f'Supports FAIR {labels} by improving discovery through reusable catalog metadata.',
        'semantic_anchor': f'Supports FAIR {labels} by linking records to reusable semantic identifiers and interpretation anchors.',
        'technical_metadata': f'Supports FAIR {labels} by exposing representation and conformance details needed for reuse.',
        'access_policy': f'Supports FAIR {labels} by clarifying access, licensing, and reuse conditions.',
        'quality_provenance': f'Supports FAIR {labels} by documenting origin, quality, and trust context.',
        'lifecycle_context': f'Supports FAIR {labels} by making construction phase context searchable and reusable.',
    }.get(requirement_type, f'Supports FAIR {labels} through reviewable metadata requirements.')


def metadata_need_for_requirement(requirement_type: str, statement: str) -> str:
    lowered = statement.lower()
    if 'aas' in lowered and 'semantic' in lowered:
        return 'reference AAS semantic identifiers'
    if 'aas' in lowered or 'submodel' in lowered:
        return 'reference AAS submodels'
    if 'ifc' in lowered and 'schema' in lowered:
        return 'indicate IFC schema version or conformance target'
    if 'ifc' in lowered:
        return 'reference IFC entity classes'
    if 'lifecycle' in lowered or 'maintenance' in lowered:
        return 'indicate construction lifecycle phase'
    if 'license' in lowered or 'access' in lowered:
        return 'describe access and reuse conditions'
    if 'format' in lowered or 'distribution' in lowered:
        return 'describe distribution format and representation'
    return {
        'descriptive_metadata': 'provide descriptive dataset metadata',
        'semantic_anchor': 'provide semantic anchors',
        'technical_metadata': 'describe technical representation metadata',
        'access_policy': 'describe access and reuse conditions',
        'quality_provenance': 'describe provenance and quality context',
        'lifecycle_context': 'indicate construction lifecycle phase',
    }.get(requirement_type, 'describe dataset for discovery')


def value_kind_for_requirement(requirement_type: str) -> str:
    return {
        'semantic_anchor': 'uri',
        'technical_metadata': 'uri',
        'access_policy': 'uri',
        'lifecycle_context': 'controlled_concept',
        'descriptive_metadata': 'literal',
        'quality_provenance': 'literal',
    }.get(requirement_type, 'unknown')


def terms_for_requirement(requirement: CandidateRequirement) -> list[str]:
    need = (requirement.normalized_intent.metadata_need or '').lower()
    if 'aas semantic' in need:
        return ['cx:semanticAnchor', 'cx:hasAASSubmodel']
    if 'aas submodel' in need:
        return ['cx:hasAASSubmodel']
    if 'ifc schema' in need or 'conformance' in need:
        return ['dcterms:conformsTo', 'dcterms:format', 'dcat:mediaType']
    if 'ifc entity' in need:
        return ['cx:hasIFCEntity']
    if 'asset type' in need:
        return ['cx:describesAssetType', 'dcat:theme']
    if 'lifecycle' in need:
        return ['cx:hasLifecyclePhase', 'dcat:theme']
    if 'access' in need or 'license' in need:
        return ['dcterms:license', 'dcterms:accessRights', 'dcat:accessURL']
    if 'distribution' in need or 'format' in need:
        return ['dcat:distribution', 'dcterms:format', 'dcat:mediaType', 'dcat:downloadURL']
    if 'provenance' in need or 'quality' in need:
        return ['dcterms:provenance', 'prov:wasDerivedFrom', 'cx:hasDataSourceSystem']
    return ['dcterms:title', 'dcterms:description', 'dcat:keyword', 'dcat:theme']


def metadata_action_rationale(metadata_need: str, terms: list[str]) -> str:
    if any(term.startswith('cx:') for term in terms):
        return f'{metadata_need} is construction-specific and may need Construct-DCAT profile terms or extensions.'
    return f'{metadata_need} can reuse established DCAT/DCAT-AP or provenance terms.'


def property_from_candidate_term(term: str) -> str | None:
    return {
        'dcterms:title': 'title',
        'dcterms:description': 'description',
        'dcterms:publisher': 'publisher',
        'dcterms:license': 'license',
        'dcterms:accessRights': 'accessRights',
        'dcterms:format': 'format',
        'dcterms:conformsTo': 'schemaVersion',
        'dcterms:provenance': 'provenance',
        'dcat:keyword': 'keyword',
        'dcat:theme': 'theme',
        'dcat:distribution': 'distribution',
        'dcat:accessURL': 'accessURL',
        'dcat:downloadURL': 'downloadURL',
        'dcat:mediaType': 'mediaType',
        'cx:semanticAnchor': 'semanticAnchor',
        'cx:usesOntology': 'usesOntology',
        'cx:hasLifecyclePhase': 'hasLifecyclePhase',
        'cx:describesAssetType': 'describesAssetType',
        'cx:hasAASSubmodel': 'hasAASSubmodel',
        'cx:hasIFCEntity': 'hasIFCEntity',
        'cx:hasDataSourceSystem': 'hasDataSourceSystem',
        'prov:wasDerivedFrom': 'provenance',
    }.get(term)


def properties_for_requirement(requirement: CandidateRequirement) -> list[str]:
    props: list[str] = []
    for action in requirement.candidate_metadata_actions:
        for term in action.candidate_terms:
            prop = property_from_candidate_term(term)
            if prop and prop not in props:
                props.append(prop)
    if props:
        return props
    return properties_for_category(requirement.category or category_for_requirement_type(requirement.requirement_type))


def token_jaccard(a: str, b: str) -> float:
    left = set(normalize_tokens(a))
    right = set(normalize_tokens(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def normalize_tokens(value: str) -> list[str]:
    stop = {'a', 'an', 'and', 'or', 'the', 'to', 'of', 'for', 'with', 'by', 'be', 'able', 'should'}
    return [token for token in re.findall(r'[a-z0-9]+', value.lower()) if token not in stop]


def merged_statement_for(requirements: list[CandidateRequirement]) -> str:
    resource = requirements[0].normalized_intent.resource_type
    req_type = requirements[0].requirement_type
    if req_type == 'semantic_anchor':
        return f'A dcat:{resource} should support external semantic anchors for construction-specific interpretation and discovery.'
    needs = clean_matches(requirement.normalized_intent.metadata_need for requirement in requirements)
    return f'A dcat:{resource} should support {", ".join(needs)}.'


def dedupe_evidence_units(items: Iterable[EvidenceUnit]) -> list[EvidenceUnit]:
    grouped: dict[tuple[str, str | None, str], EvidenceUnit] = {}
    for item in items:
        key = (item.artifact_name, item.locator, item.content)
        if key not in grouped:
            grouped[key] = item
        else:
            grouped[key].extracted_facts = merge_evidence(grouped[key].extracted_facts, item.extracted_facts)
            grouped[key].confidence = max(grouped[key].confidence, item.confidence)
    return sorted(grouped.values(), key=lambda item: (item.artifact_name, item.locator or '', item.content))[:400]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+|\n+', text)
    return [part.strip(' -*\t') for part in parts if part.strip(' -*\t')]


def infer_category(text: str) -> str:
    lowered = text.lower()
    for rule in TEXT_RULES:
        if any(token in lowered for token in rule['tokens']):
            return rule['category']
    return 'Dataset Metadata'


def generated_question(category: str, source: str) -> CompetencyQuestion:
    question = {
        'Dataset Metadata': 'Which datasets can be discovered by title, description, keyword, theme, publisher, and distribution metadata?',
        'Semantic Anchors': 'Which datasets are connected to reusable ontology terms, AAS semantic IDs, IFC classes, or controlled concepts?',
        'Asset Semantics': 'Which datasets describe a given construction asset type or building system?',
        'Lifecycle Information': 'Which datasets are relevant to a specific construction lifecycle phase?',
        'Technical Metadata': 'Which datasets are available in a specific format, schema version, or distribution form?',
        'Access/Policy': 'Which datasets can be reused under a given license, rights statement, or access policy?',
        'Quality Metadata': 'Which datasets provide provenance, completeness, quality, or source-system evidence?',
    }.get(category, 'Which datasets satisfy this metadata requirement?')
    return CompetencyQuestion(id=stable_id('cq', category, source), question=question, category=category, source=source)


def collect_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(collect_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(collect_keys(child))
    return keys


def extract_identifiers(value: Any) -> list[str]:
    identifiers: list[str] = []
    if isinstance(value, str):
        identifiers.append(value)
    elif isinstance(value, dict):
        for key in ['value', 'id', 'href', 'IRI', 'iri']:
            if isinstance(value.get(key), str):
                identifiers.append(value[key])
        for child in value.values():
            identifiers.extend(extract_identifiers(child))
    elif isinstance(value, list):
        for child in value:
            identifiers.extend(extract_identifiers(child))
    return clean_matches(identifiers)


def extract_labels(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key in ['text', 'value', 'preferredName', 'shortName']:
            if isinstance(value.get(key), str):
                return [value[key]]
        return [str(item) for key, item in value.items() if key.lower() not in {'language', 'lang'} and isinstance(item, str)]
    if isinstance(value, list):
        labels: list[str] = []
        for item in value:
            labels.extend(extract_labels(item))
        return clean_matches(labels)
    return []


def key_to_property(key: str) -> str | None:
    lowered = key.lower()
    mapping = {
        'title': 'title',
        'description': 'description',
        'keyword': 'keyword',
        'theme': 'theme',
        'publisher': 'publisher',
        'distribution': 'distribution',
        'accessurl': 'accessURL',
        'downloadurl': 'downloadURL',
        'mediatype': 'mediaType',
        'format': 'format',
        'license': 'license',
        'accessrights': 'accessRights',
        'conformsto': 'schemaVersion',
    }
    normalized = lowered.replace(':', '').replace('_', '').replace('-', '')
    return mapping.get(normalized)


def stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha1('|'.join(str(part) for part in parts).encode('utf-8')).hexdigest()[:10]
    return f'{prefix}-{digest}'


def looks_like_uri(value: str) -> bool:
    return value.startswith(('http://', 'https://', 'urn:', 'irdi:', '0173-'))


def compact_uri(uri: str) -> str:
    prefixes = {
        'http://purl.org/dc/terms/': 'dcterms:',
        'http://www.w3.org/ns/dcat#': 'dcat:',
        'https://w3id.org/cx#': 'cx:',
        'http://www.w3.org/2004/02/skos/core#': 'skos:',
        'http://www.w3.org/ns/prov#': 'prov:',
    }
    for base, prefix in prefixes.items():
        if uri.startswith(base):
            return prefix + uri.removeprefix(base)
    return f'<{uri}>'


def slot_name_from_uri(uri: str) -> str:
    local = re.split(r'[#/]', uri.rstrip('/'))[-1]
    if local:
        return local[:1].lower() + local[1:]
    return 'generatedSlot'


def term_for_uri(uri: str) -> dict[str, Any] | None:
    for term in PROPERTY_CATALOG.values():
        if term['uri'] == uri:
            return term
    return None


def range_for_term(term: dict[str, Any] | None, uri: str) -> str:
    if term:
        return term.get('range', 'string')
    if uri.startswith(('http://', 'https://')):
        return 'anyURI'
    return 'string'


def dedupe_attributes(items: Iterable[ExtractedAttribute]) -> list[ExtractedAttribute]:
    grouped: dict[tuple[str, str, str], ExtractedAttribute] = {}
    for item in items:
        key = (item.source, item.path, item.value)
        if key not in grouped:
            grouped[key] = item
        else:
            grouped[key].confidence = max(grouped[key].confidence, item.confidence)
    return sorted(grouped.values(), key=lambda item: (item.source, item.category, item.path))[:300]


def dedupe_requirements(items: Iterable[CandidateRequirement]) -> list[CandidateRequirement]:
    grouped: dict[tuple[str, str, str], CandidateRequirement] = {}
    for item in items:
        statement = item.normalized_statement or item.description or item.title or item.id
        category = item.category or category_for_requirement_type(item.requirement_type)
        key = (item.requirement_type, item.normalized_intent.resource_type, re.sub(r'\s+', ' ', statement.lower()).strip())
        if key not in grouped:
            grouped[key] = item
            grouped[key].category = category
        else:
            grouped[key].evidence = merge_evidence(grouped[key].evidence, item.evidence)
            grouped[key].source_evidence = merge_source_evidence(grouped[key].source_evidence, item.source_evidence)
            grouped[key].fair_dimensions = merge_evidence(grouped[key].fair_dimensions, item.fair_dimensions)
            grouped[key].candidate_metadata_actions = merge_metadata_actions(grouped[key].candidate_metadata_actions, item.candidate_metadata_actions)
            grouped[key].confidence = max(grouped[key].confidence, item.confidence)
    return sorted(grouped.values(), key=lambda item: (item.category or '', item.requirement_type, item.title or item.normalized_statement or item.id))


def dedupe_metadata(items: Iterable[MetadataCandidate]) -> list[MetadataCandidate]:
    grouped: dict[tuple[str, str], MetadataCandidate] = {}
    for item in items:
        key = (item.property, item.category)
        if key not in grouped:
            grouped[key] = item
        else:
            grouped[key].evidence = merge_evidence(grouped[key].evidence, item.evidence)
            grouped[key].confidence = max(grouped[key].confidence, item.confidence)
    return sorted(grouped.values(), key=lambda item: (item.category, item.property))


def dedupe_semantic(items: Iterable[SemanticCandidate]) -> list[SemanticCandidate]:
    grouped: dict[tuple[str, str], SemanticCandidate] = {}
    for item in items:
        key = (item.kind, item.identifier or item.label.lower())
        if key not in grouped:
            grouped[key] = item
        else:
            grouped[key].evidence = merge_evidence(grouped[key].evidence, item.evidence)
            grouped[key].confidence = max(grouped[key].confidence, item.confidence)
    return sorted(grouped.values(), key=lambda item: (item.kind, item.label))[:80]


def dedupe_questions(items: Iterable[CompetencyQuestion]) -> list[CompetencyQuestion]:
    seen: set[str] = set()
    result: list[CompetencyQuestion] = []
    for item in items:
        if item.question not in seen:
            seen.add(item.question)
            result.append(item)
    return result


def dedupe_recommendations(items: Iterable[ReuseRecommendation]) -> list[ReuseRecommendation]:
    grouped: dict[str, ReuseRecommendation] = {}
    for item in items:
        key = item.term_uri
        if key not in grouped:
            grouped[key] = item
        else:
            grouped[key].confidence = max(grouped[key].confidence, item.confidence)
            grouped[key].rationale = grouped[key].rationale if item.rationale in grouped[key].rationale else f'{grouped[key].rationale} {item.rationale}'
    return sorted(grouped.values(), key=lambda item: (item.priority, item.label))



def merge_source_evidence(left: list[SourceEvidence], right: list[SourceEvidence]) -> list[SourceEvidence]:
    grouped: dict[str, SourceEvidence] = {}
    for item in [*left, *right]:
        key = f'{item.evidence_unit_id}:{item.locator or ""}:{item.evidence_text}'
        grouped.setdefault(key, item)
    return list(grouped.values())[:12]


def merge_metadata_actions(left: list[CandidateMetadataAction], right: list[CandidateMetadataAction]) -> list[CandidateMetadataAction]:
    grouped: dict[tuple[str, tuple[str, ...]], CandidateMetadataAction] = {}
    for item in [*left, *right]:
        key = (item.action, tuple(item.candidate_terms))
        grouped.setdefault(key, item)
    return list(grouped.values())[:8]


def merge_evidence(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    for item in [*left, *right]:
        if item and item not in merged:
            merged.append(item)
    return merged[:8]
