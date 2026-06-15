import type { SchemaModel } from '../types';

export type ArtifactPayload = {
  name: string;
  media_type?: string;
  content: string;
  content_encoding?: 'text' | 'base64';
};

export type ExtractionStrategy = 'rules' | 'llm' | 'hybrid';
export type ValidationStatus = 'valid' | 'missing_evidence' | 'invalid_schema' | 'unknown_term' | 'resource_mismatch' | 'needs_review';
export type RequirementScope =
  | 'profile_element'
  | 'obligation_level'
  | 'controlled_vocabulary'
  | 'validation_constraint'
  | 'documentation_guidance'
  | 'example_requirement'
  | 'unknown';

export type UserTask = {
  id: string;
  statement: string;
  kind: 'competency_question' | 'user_task' | 'stakeholder_need';
  stakeholder?: string | null;
  source?: string;
};

export type ExtractionProvenance = {
  strategy: ExtractionStrategy;
  extractor: string;
  model_id?: string | null;
  prompt_version?: string | null;
  created_at?: string | null;
  evidence_verified?: boolean | null;
  notes: string[];
  editor_history: Array<Record<string, unknown>>;
};

export type AnalysisRequest = {
  source_corpus_id?: string | null;
  text?: string;
  artifacts: ArtifactPayload[];
  user_tasks?: UserTask[];
  strategy?: ExtractionStrategy;
  llm_model?: string | null;
  cq_guided?: boolean;
};

export type ArtifactSummary = {
  name: string;
  kind: string;
  evidence_count: number;
  notes: string[];
};

export type EvidenceUnit = {
  id: string;
  source_id: string;
  artifact_name: string;
  artifact_kind: string;
  locator?: string | null;
  content: string;
  extracted_facts: string[];
  confidence: number;
};

export type SourceEvidence = {
  evidence_unit_id: string;
  source_id: string;
  artifact_name: string;
  artifact_kind: string;
  locator?: string | null;
  evidence_text: string;
  extracted_facts: string[];
};

export type NormalizedIntent = {
  resource_type: 'Catalog' | 'Dataset' | 'Distribution' | 'DataService' | 'Agent' | 'Concept' | 'Unknown';
  metadata_need: string;
  value_kind: 'literal' | 'uri' | 'controlled_concept' | 'class_reference' | 'date' | 'agent' | 'distribution' | 'unknown';
  obligation_hint: 'mandatory' | 'recommended' | 'optional' | 'unknown';
};

export type CandidateMetadataAction = {
  action:
    | 'reuse_existing_term'
    | 'specialize_existing_term'
    | 'create_extension'
    | 'add_constraint'
    | 'add_usage_note'
    | 'no_action';
  target_class?: string | null;
  candidate_terms: string[];
  rationale: string;
  constraint_hint?: {
    cardinality?: string | null;
    value_kind: NormalizedIntent['value_kind'];
    datatype_or_class?: string | null;
    obligation: NormalizedIntent['obligation_hint'];
  } | null;
  source_requirement_id?: string | null;
};

export type CandidateRequirement = {
  id: string;
  raw_statement?: string | null;
  normalized_statement?: string | null;
  requirement_type:
    | 'descriptive_metadata'
    | 'semantic_anchor'
    | 'technical_metadata'
    | 'access_policy'
    | 'quality_provenance'
    | 'lifecycle_context'
    | 'controlled_vocabulary'
    | 'validation_constraint'
    | 'competency_question'
    | 'unknown';
  source_evidence: SourceEvidence[];
  normalized_intent: NormalizedIntent;
  fair_dimensions: Array<'F' | 'A' | 'I' | 'R'>;
  fair_rationale?: string | null;
  candidate_metadata_actions: CandidateMetadataAction[];
  supports_user_tasks: string[];
  requires_multiple_elements?: boolean;
  validation_evidence: string[];
  validation_status: ValidationStatus;
  requirement_scope: RequirementScope;
  provenance?: ExtractionProvenance | null;
  status: 'candidate' | 'approved' | 'rejected' | 'merged' | 'needs_review';
  review_notes?: string | null;
  merged_from: string[];
  title?: string | null;
  description?: string | null;
  category?: string | null;
  source?: string | null;
  evidence: string[];
  confidence: number;
};

export type DuplicateGroup = {
  id: string;
  requirement_ids: string[];
  suggested_merged_statement: string;
  reason: string;
  confidence: number;
};

export type SemanticCandidate = {
  id: string;
  label: string;
  kind: string;
  identifier?: string | null;
  source: string;
  evidence: string[];
  confidence: number;
};

export type ExtractedAttribute = {
  id: string;
  source: string;
  path: string;
  label: string;
  value: string;
  category: string;
  value_type: string;
  confidence: number;
};

export type MetadataCandidate = {
  id: string;
  property: string;
  label: string;
  category: string;
  range: string;
  requirement_level: 'mandatory' | 'recommended' | 'optional';
  source: string;
  evidence: string[];
  confidence: number;
};

export type CompetencyQuestion = {
  id: string;
  question: string;
  category: string;
  source: string;
  evidence?: string | null;
};

export type AnalysisResponse = {
  strategy: ExtractionStrategy;
  study_setup: Record<string, unknown>;
  user_tasks: UserTask[];
  artifacts: ArtifactSummary[];
  evidence_units: EvidenceUnit[];
  extracted_attributes: ExtractedAttribute[];
  requirements: CandidateRequirement[];
  duplicate_groups: DuplicateGroup[];
  semantic_candidates: SemanticCandidate[];
  metadata_candidates: MetadataCandidate[];
  competency_questions: CompetencyQuestion[];
  funnel_metrics: Record<string, unknown>;
  warnings: string[];
};

export type ReuseRecommendation = {
  id: string;
  label: string;
  vocabulary: string;
  term_uri: string;
  priority: number;
  action: 'reuse' | 'profile' | 'extension';
  requirement_id?: string | null;
  candidate_id?: string | null;
  rationale: string;
  confidence: number;
};

export type RecommendationResponse = {
  recommendations: ReuseRecommendation[];
  extension_candidates: MetadataCandidate[];
};

export type ConstraintGenerationResponse = {
  shacl: string;
  profile_draft: SchemaModel;
  validation_notes: string[];
};

export type Rq1LocalMergeEvent = {
  timestamp: string;
  source_requirement_ids: string[];
  merged_requirement_id: string;
  normalized_statement: string;
  suggested_statement_used: boolean;
};

export type Rq1LocalSplitEvent = {
  timestamp: string;
  source_requirement_id: string;
  split_requirement_ids: string[];
  source_statement: string;
};

export type Rq1DatasetExport = {
  schema_version: string;
  export_kind?: 'reviewed_frontend_state' | 'service_generated';
  generated_at: string;
  source_corpus_id?: string | null;
  reviewer_id?: string;
  session_id?: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  study_setup?: Record<string, unknown>;
  rq1_codebook?: Record<string, unknown>;
  strategy_requested: ExtractionStrategy;
  strategy_used: ExtractionStrategy;
  summary_metrics: Record<string, unknown>;
  requirements: CandidateRequirement[];
  evidence_units: EvidenceUnit[];
  duplicate_groups: DuplicateGroup[];
  duplicate_groups_original?: DuplicateGroup[];
  local_merge_events?: Rq1LocalMergeEvent[];
  local_split_events?: Rq1LocalSplitEvent[];
  user_tasks: UserTask[];
  funnel_metrics?: Record<string, unknown>;
  warnings: string[];
  review_editor_history: Array<Record<string, unknown>>;
};

async function postJson<T>(endpoint: string, payload: unknown): Promise<T> {
  const response = await fetch(`/api/requirements/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()) as T;
}

export function analyzeArtifacts(payload: AnalysisRequest) {
  return postJson<AnalysisResponse>('analyze-artifacts', payload);
}

export function extractRequirements(payload: AnalysisRequest) {
  return postJson<AnalysisResponse>('extract-requirements', payload);
}

export function exportRq1Dataset(payload: AnalysisRequest) {
  return postJson<Rq1DatasetExport>('export-rq1-dataset', payload);
}

export function recommendReuse(analysis: AnalysisResponse) {
  return postJson<RecommendationResponse>('recommend-reuse', { analysis });
}

export function generateShacl(analysis: AnalysisResponse, recommendations: ReuseRecommendation[], selectedRecommendationIds: string[]) {
  return postJson<ConstraintGenerationResponse>('generate-shacl', {
    analysis,
    recommendations,
    selected_recommendation_ids: selectedRecommendationIds,
  });
}

export type ProfileChange = {
  id: string;
  requirement_id: string;
  change_type:
    | 'reuse_property'
    | 'specialize_property'
    | 'create_extension_property'
    | 'create_profile_class'
    | 'add_constraint'
    | 'add_usage_note'
    | 'add_controlled_vocabulary';
  target_class: string;
  term_uri?: string | null;
  slot_name?: string | null;
  class_name?: string | null;
  range?: string | null;
  required?: boolean | null;
  multivalued?: boolean | null;
  obligation_level: 'mandatory' | 'recommended' | 'optional' | 'unknown';
  rationale: string;
  source_vocabulary?: string | null;
  evidence_ids: string[];
  source_requirement_ids: string[];
  review_status: 'candidate' | 'accepted' | 'rejected' | 'needs_review';
  selected?: boolean;
  alternative_terms?: string[];
  warnings: string[];
};

export type ProfileGenerationMode = 'minimal' | 'exploratory';

export type ProfileChangeSet = {
  id: string;
  source_requirement_set_id?: string | null;
  created_at: string;
  profile_base: string;
  profile_namespace: string;
  profile_prefix: string;
  mode: ProfileGenerationMode;
  changes: ProfileChange[];
  discovered_candidate_terms: string[];
  review_history: Array<Record<string, unknown>>;
  warnings: string[];
  summary_metrics: Record<string, unknown>;
};

export type ProfileGenerationResponse = {
  profile_change_set: ProfileChangeSet;
  profile_draft: SchemaModel;
  shacl: string;
  validation_notes: string[];
};

export type RQ2Package = {
  schema_version: string;
  generated_at: string;
  base_profile: string;
  source_requirement_set_id?: string | null;
  approved_requirement_count: number;
  profile_change_set: ProfileChangeSet;
  profile_draft_linkml: SchemaModel;
  shacl: string;
  provenance_mapping: Array<{
    requirement_id: string;
    profile_element: string;
    change_id: string;
    evidence_unit_ids: string[];
  }>;
  warnings: string[];
  validation_notes: string[];
};

export function generateProfileChanges(payload: {
  requirements: CandidateRequirement[];
  approved_only?: boolean;
  mode?: ProfileGenerationMode;
  base_profile?: string;
}) {
  return postJson<ProfileChangeSet>('generate-profile-changes', payload);
}

export function generateProfileDraft(payload: { profile_change_set: ProfileChangeSet; accepted_only?: boolean; base_schema?: SchemaModel }) {
  return postJson<ProfileGenerationResponse>('generate-profile-draft', payload);
}

export function exportRq2Package(payload: {
  profile_change_set: ProfileChangeSet;
  base_schema?: SchemaModel;
  source_requirement_set_id?: string | null;
  approved_requirement_count?: number;
  accepted_only?: boolean;
}) {
  return postJson<RQ2Package>('export-rq2-package', payload);
}
