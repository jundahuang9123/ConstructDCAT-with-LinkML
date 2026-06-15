from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from ..models import (
    AnalysisRequest,
    CandidateMetadataAction,
    CandidateRequirement,
    EvidenceUnit,
    ExtractionProvenance,
    NormalizedIntent,
    SourceEvidence,
    UserTask,
)
from ..rq1_codebook import codebook_prompt_text
from .client import LLMClient

PROMPT_VERSION = 'rrs-extract-v1'

MAX_CHARS_PER_EVIDENCE_UNIT = 1200
MAX_TOTAL_CHARS = 60000

REQUIREMENT_TYPES = [
    'descriptive_metadata',
    'semantic_anchor',
    'technical_metadata',
    'access_policy',
    'quality_provenance',
    'lifecycle_context',
    'controlled_vocabulary',
    'validation_constraint',
    'competency_question',
]

RESOURCE_TYPES = {'Catalog', 'Dataset', 'Distribution', 'DataService', 'Agent', 'Concept'}
VALUE_KINDS = {'literal', 'uri', 'controlled_concept', 'class_reference', 'date', 'agent', 'distribution'}
OBLIGATIONS = {'mandatory', 'recommended', 'optional'}
ACTIONS = {'reuse_existing_term', 'specialize_existing_term', 'create_extension', 'add_constraint', 'add_usage_note', 'no_action'}
REQUIREMENT_SCOPES = {
    'profile_element',
    'obligation_level',
    'controlled_vocabulary',
    'validation_constraint',
    'documentation_guidance',
    'example_requirement',
    'unknown',
}

SYSTEM_PROMPT = f"""You are a metadata profile engineering assistant supporting a reuse-first, \
requirements-driven workflow for building DCAT/DCAT-AP-compatible application profiles \
(FAIR-oriented dataset cataloging, construction domain and beyond).

You receive heterogeneous source materials: free-text requirement descriptions, competency \
questions and user tasks from domain experts, AAS (Asset Administration Shell) structures, \
IFC snippets, existing DCAT/RDF metadata, and standards or profile excerpts.

Your task: extract CANDIDATE profile-design requirements as structured, traceable records. \
You are a bounded assistant - every record will be reviewed by a human expert before acceptance.

Rules:
1. Each requirement must be a single, testable profile-design statement of the form \
"A dcat:Dataset (or dcat:Distribution / dcat:Catalog / dcat:DataService) should/must ...".
2. EVIDENCE MUST BE VERBATIM. Every evidence quote must cite an evidence_unit_id and must be \
an exact, contiguous substring copied character-for-character from that evidence unit content. \
Never paraphrase, never summarize, never merge text from different evidence units into one quote. \
Unknown evidence_unit_id values and fabricated quotes are discarded.
3. Reuse first: prefer existing DCAT/DCAT-AP/Dublin Core terms (dcterms:, dcat:, foaf:, prov:, \
skos:). Suggest a profile-specific extension term (cx: prefix) only when no standard term fits, \
and say why in the action rationale.
4. requirement_type must be one of: {', '.join(REQUIREMENT_TYPES)}.
5. requirement_scope must be one of: {', '.join(sorted(REQUIREMENT_SCOPES))}.
6. fair_dimensions uses letters F, A, I, R (Findable, Accessible, Interoperable, Reusable); \
include only dimensions the requirement genuinely supports, with a one-sentence rationale.
7. If user tasks / competency questions are provided (each with an id), list the ids of the \
tasks each requirement supports in supports_user_tasks. Only link a task if the requirement \
genuinely helps answer or accomplish it.
8. Do not invent requirements that have no support in the sources. Fewer, well-grounded \
records are better than many speculative ones.
9. Normalize: if several places express the same need, produce ONE requirement with multiple \
evidence quotes rather than near-duplicates.
10. Extract catalog-level discovery requirements, not every internal term, object, property, \
geometry detail, calculation, or measurement value from source artifacts."""


class LLMEvidence(BaseModel):
    evidence_unit_id: str = Field(description='ID of the evidence unit being cited')
    quote: str = Field(description='Verbatim contiguous substring copied from that evidence unit content')


class LLMRequirement(BaseModel):
    statement: str = Field(description='Normalized profile-design statement')
    requirement_type: str = Field(description='One of the allowed requirement types')
    requirement_scope: str = Field(description='One of the allowed requirement scopes')
    resource_type: str = Field(description='Dataset | Distribution | Catalog | DataService | Agent | Concept')
    metadata_need: str = Field(description='Short phrase naming the metadata need')
    value_kind: str = Field(description='literal | uri | controlled_concept | class_reference | date | agent | distribution')
    obligation: str = Field(description='mandatory | recommended | optional')
    fair_dimensions: list[str] = Field(default_factory=list)
    fair_rationale: str = ''
    action: str = Field(description='reuse_existing_term | specialize_existing_term | create_extension | add_constraint | add_usage_note')
    candidate_terms: list[str] = Field(default_factory=list, description='Prefixed candidate terms, e.g. dcterms:title, dcat:theme, cx:hasLifecyclePhase')
    action_rationale: str = ''
    supports_user_tasks: list[str] = Field(default_factory=list)
    evidence: list[LLMEvidence] = Field(default_factory=list)
    confidence: float = 0.7


class LLMExtractionResult(BaseModel):
    requirements: list[LLMRequirement] = Field(default_factory=list)


def extract_with_llm(
    payload: AnalysisRequest,
    client: LLMClient,
) -> tuple[list[CandidateRequirement], list[str]]:
    """Run LLM-assisted requirement extraction over the request sources.

    Returns candidate requirements (with provenance and verified evidence)
    plus human-readable warnings (e.g. discarded hallucinated quotes).
    """
    evidence_units = build_evidence_units(payload)
    if not evidence_units:
        return [], ['No analyzable source content was provided for LLM extraction.']

    user_prompt, prompt_warnings = build_user_prompt(evidence_units, payload.user_tasks)
    result = client.generate_structured(system=SYSTEM_PROMPT, user=user_prompt, output_model=LLMExtractionResult)

    warnings: list[str] = list(prompt_warnings)
    requirements: list[CandidateRequirement] = []
    evidence_by_id = {unit.id: unit for unit in evidence_units}
    known_task_ids = {task.id for task in payload.user_tasks}
    created_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    description = client.describe()

    for item in result.requirements:
        requirement = convert_requirement(
            item,
            evidence_by_id,
            known_task_ids,
            warnings,
            provenance=ExtractionProvenance(
                strategy='llm',
                extractor=f'llm-extractor/{PROMPT_VERSION}',
                model_id=description.get('model'),
                prompt_version=PROMPT_VERSION,
                created_at=created_at,
            ),
        )
        if requirement is not None:
            requirements.append(requirement)
    return requirements, warnings


def build_evidence_units(payload: AnalysisRequest) -> list[EvidenceUnit]:
    from ..service import extract_evidence_units

    return extract_evidence_units(payload)


def build_user_prompt(evidence_units: list[EvidenceUnit], user_tasks: list[UserTask]) -> tuple[str, list[str]]:
    parts: list[str] = [codebook_prompt_text(), '']
    warnings: list[str] = []
    if user_tasks:
        parts.append('USER TASKS / COMPETENCY QUESTIONS (reference these ids in supports_user_tasks):')
        for task in user_tasks:
            stakeholder = f' [stakeholder: {task.stakeholder}]' if task.stakeholder else ''
            parts.append(f'- {task.id} ({task.kind}){stakeholder}: {task.statement}')
        parts.append('')

    parts.append('EVIDENCE UNITS (cite evidence_unit_id plus a verbatim quote from content):')
    total = 0
    omitted_ids: list[str] = []
    truncated_ids: list[str] = []
    for unit in evidence_units:
        content = unit.content
        if len(content) > MAX_CHARS_PER_EVIDENCE_UNIT:
            content = content[:MAX_CHARS_PER_EVIDENCE_UNIT]
            truncated_ids.append(unit.id)
        if total + len(content) > MAX_TOTAL_CHARS:
            remaining = MAX_TOTAL_CHARS - total
            if remaining <= 0:
                parts.append(f'--- evidence_unit_id: {unit.id} [omitted: input budget exhausted]')
                omitted_ids.append(unit.id)
                continue
            content = content[:remaining]
            truncated_ids.append(unit.id)
        total += len(content)
        parts.append(f'--- evidence_unit_id: {unit.id}')
        parts.append(f'artifact_name: {unit.artifact_name}')
        parts.append(f'artifact_kind: {unit.artifact_kind}')
        parts.append(f'locator: {unit.locator or ""}')
        parts.append(f'extracted_facts: {"; ".join(unit.extracted_facts)}')
        parts.append('content:')
        parts.append(content)
        parts.append('--- end evidence unit')
        parts.append('')

    parts.append('Extract the candidate profile-design requirements from these evidence units now.')
    if truncated_ids:
        unique_truncated_ids = list(dict.fromkeys(truncated_ids))
        warnings.append(
            'input_budget_truncation: '
            f'{len(unique_truncated_ids)} evidence unit(s) were truncated in the LLM prompt due to input budget: '
            f'{", ".join(unique_truncated_ids[:12])}'
        )
    if omitted_ids:
        warnings.append(
            'input_budget_omission: '
            f'{len(omitted_ids)} evidence unit(s) were omitted from the LLM prompt due to input budget: '
            f'{", ".join(omitted_ids[:12])}'
        )
    return '\n'.join(parts), warnings


def convert_requirement(
    item: LLMRequirement,
    evidence_by_id: dict[str, EvidenceUnit],
    known_task_ids: set[str],
    warnings: list[str],
    provenance: ExtractionProvenance,
) -> CandidateRequirement | None:
    from ..service import category_for_requirement_type, stable_id, title_for_statement, validate_requirement

    statement = item.statement.strip()
    if not statement:
        return None

    verified_evidence: list[SourceEvidence] = []
    dropped = 0
    for evidence in item.evidence:
        unit = evidence_by_id.get(evidence.evidence_unit_id)
        if unit is None:
            dropped += 1
            warnings.append(
                f"Discarded evidence for '{title_for_statement(statement)}' "
                f'(unknown evidence_unit_id={evidence.evidence_unit_id}): "{truncate(evidence.quote, 120)}"'
            )
            continue
        located = locate_quote(evidence.quote, unit)
        if located is None:
            dropped += 1
            warnings.append(
                f"Discarded unverifiable evidence quote for '{title_for_statement(statement)}' "
                f'(not found verbatim in {evidence.evidence_unit_id}): "{truncate(evidence.quote, 120)}"'
            )
            continue
        start, end, quote = located
        verified_evidence.append(
            SourceEvidence(
                evidence_unit_id=unit.id,
                source_id=unit.source_id,
                artifact_name=unit.artifact_name,
                artifact_kind=unit.artifact_kind,
                locator=f'{unit.locator or "content"};chars:{start}-{end}',
                evidence_text=quote,
                extracted_facts=unit.extracted_facts,
            )
        )

    evidence_verified = dropped == 0 and bool(verified_evidence)
    provenance = provenance.model_copy(update={'evidence_verified': evidence_verified})
    if not verified_evidence:
        provenance.notes.append('All evidence quotes failed verbatim verification; requirement needs manual review.')

    requirement_type = item.requirement_type if item.requirement_type in REQUIREMENT_TYPES else 'unknown'
    resource_type = item.resource_type if item.resource_type in RESOURCE_TYPES else 'Dataset'
    value_kind = item.value_kind if item.value_kind in VALUE_KINDS else 'unknown'
    obligation = item.obligation if item.obligation in OBLIGATIONS else 'unknown'
    action = item.action if item.action in ACTIONS else 'reuse_existing_term'
    requirement_scope = item.requirement_scope if item.requirement_scope in REQUIREMENT_SCOPES else 'unknown'
    fair = [dim for dim in item.fair_dimensions if dim in {'F', 'A', 'I', 'R'}]

    unknown_tasks = [task_id for task_id in item.supports_user_tasks if known_task_ids and task_id not in known_task_ids]
    if unknown_tasks:
        warnings.append(f"Requirement '{title_for_statement(statement)}' referenced unknown user task ids: {', '.join(unknown_tasks)}")
    supported_tasks = [task_id for task_id in item.supports_user_tasks if task_id in known_task_ids]

    confidence = max(0.05, min(0.95, item.confidence))
    if not evidence_verified:
        confidence = min(confidence, 0.4)

    category = category_for_requirement_type(requirement_type)
    requirement = CandidateRequirement(
        id=stable_id('req', 'llm', statement, *(unit.evidence_unit_id for unit in verified_evidence[:4])),
        raw_statement='; '.join(unit.evidence_text for unit in verified_evidence[:3]) or statement,
        normalized_statement=statement,
        requirement_type=requirement_type,
        requirement_scope=requirement_scope,
        source_evidence=verified_evidence,
        normalized_intent=NormalizedIntent(
            resource_type=resource_type,
            metadata_need=item.metadata_need or 'describe dataset for discovery',
            value_kind=value_kind,
            obligation_hint=obligation,
        ),
        fair_dimensions=fair,
        fair_rationale=item.fair_rationale or None,
        candidate_metadata_actions=[
            CandidateMetadataAction(
                action=action,
                target_class=resource_type,
                candidate_terms=item.candidate_terms,
                rationale=item.action_rationale or 'Proposed by LLM-assisted extraction; review before acceptance.',
            )
        ],
        supports_user_tasks=supported_tasks,
        provenance=provenance,
        validation_status='valid' if evidence_verified else 'missing_evidence',
        status='candidate',
        title=title_for_statement(statement),
        description=statement,
        category=category,
        source=', '.join(sorted({unit.artifact_name for unit in verified_evidence})) or 'llm extraction',
        evidence=[unit.evidence_text for unit in verified_evidence[:8]],
        confidence=confidence,
    )
    return validate_requirement(requirement)


def locate_quote(
    quote: str,
    unit: EvidenceUnit,
) -> tuple[int, int, str] | None:
    """Verify a quote occurs inside its cited evidence unit."""
    quote = quote.strip()
    if not quote:
        return None

    text = unit.content
    start = text.find(quote)
    if start >= 0:
        return start, start + len(quote), quote
    match = whitespace_tolerant_search(quote, text)
    if match is not None:
        start, end = match
        return start, end, text[start:end]
    return None


def whitespace_tolerant_search(quote: str, text: str) -> tuple[int, int] | None:
    tokens = quote.split()
    if not tokens:
        return None
    pattern = r'\s+'.join(re.escape(token) for token in tokens)
    try:
        match = re.search(pattern, text)
    except re.error:
        return None
    if match:
        return match.start(), match.end()
    return None


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 3] + '...'


def merge_hybrid(
    llm_requirements: list[CandidateRequirement],
    rule_requirements: list[CandidateRequirement],
) -> list[CandidateRequirement]:
    """Hybrid strategy: LLM records first, rule-based records that add new
    metadata needs appended as grounding. Duplicate detection downstream
    surfaces remaining overlaps for the reviewer."""
    from ..service import token_jaccard

    merged = list(llm_requirements)
    for rule_requirement in rule_requirements:
        need = rule_requirement.normalized_intent.metadata_need
        if any(token_jaccard(need, existing.normalized_intent.metadata_need) >= 0.6 for existing in merged):
            continue
        merged.append(rule_requirement)
    return merged
