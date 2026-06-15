import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react';
import { AlertTriangle, CheckCircle2, Download, FileCode, FileSearch, GitMerge, RefreshCw, Search, SplitSquareHorizontal, Wand2, XCircle } from 'lucide-react';
import {
  analyzeArtifacts,
  exportRq2Package,
  extractRequirements,
  generateProfileChanges,
  generateProfileDraft,
  recommendReuse,
  type AnalysisRequest,
  type AnalysisResponse,
  type ArtifactPayload,
  type CandidateMetadataAction,
  type CandidateRequirement,
  type ExtractedAttribute,
  type ExtractionStrategy,
  type ExtractionProvenance,
  type NormalizedIntent,
  type ProfileChangeSet,
  type ProfileGenerationMode,
  type RequirementScope,
  type Rq1DatasetExport,
  type Rq1LocalMergeEvent,
  type Rq1LocalSplitEvent,
  type ReuseRecommendation,
  type SourceEvidence,
  type UserTask,
  type ValidationStatus,
} from '../lib/requirementApi';
import { downloadText } from '../lib/schemaApi';
import { useEditorStore } from '../store';
import type { SchemaModel } from '../types';

type RequirementWorkbenchProps = {
  initialView: 'requirements' | 'reuse';
  onStatus: (status: string) => void;
};

type WorkbenchView = 'requirements' | 'reuse' | 'changes' | 'constraints';
type RequirementStatus = CandidateRequirement['status'];
type RequirementType = CandidateRequirement['requirement_type'];
type FairDimension = CandidateRequirement['fair_dimensions'][number];
type EditorHistoryAction = 'edit' | 'approve' | 'reject' | 'mark_needs_review' | 'edit_candidate_metadata_action';

const SAMPLE_TEXT =
  'Datasets should indicate the construction asset type they describe. Metadata should include lifecycle phase, access conditions, format, schema version, and semantic anchors to AAS submodels or IFC entities.';

const ARTIFACT_ACCEPT = '.txt,.md,.json,.aasx,.jsonld,.ttl,.rdf,.owl,.ifc,.ifcspf';
const FAIR_DIMENSIONS: FairDimension[] = ['F', 'A', 'I', 'R'];
const REQUIREMENT_TYPES: RequirementType[] = [
  'descriptive_metadata',
  'semantic_anchor',
  'technical_metadata',
  'access_policy',
  'quality_provenance',
  'lifecycle_context',
  'controlled_vocabulary',
  'validation_constraint',
  'competency_question',
  'unknown',
];
const STATUS_OPTIONS: RequirementStatus[] = ['candidate', 'approved', 'needs_review', 'rejected', 'merged'];
const VALIDATION_STATUS_OPTIONS: ValidationStatus[] = ['valid', 'missing_evidence', 'invalid_schema', 'unknown_term', 'resource_mismatch', 'needs_review'];
const REQUIREMENT_SCOPE_OPTIONS: RequirementScope[] = [
  'profile_element',
  'obligation_level',
  'controlled_vocabulary',
  'validation_constraint',
  'documentation_guidance',
  'example_requirement',
  'unknown',
];
const RESOURCE_TYPES: NormalizedIntent['resource_type'][] = ['Dataset', 'Distribution', 'Catalog', 'DataService', 'Agent', 'Concept', 'Unknown'];
const VALUE_KINDS: NormalizedIntent['value_kind'][] = ['literal', 'uri', 'controlled_concept', 'class_reference', 'date', 'agent', 'distribution', 'unknown'];
const OBLIGATION_HINTS: NormalizedIntent['obligation_hint'][] = ['mandatory', 'recommended', 'optional', 'unknown'];
const METADATA_ACTIONS: CandidateMetadataAction['action'][] = [
  'reuse_existing_term',
  'specialize_existing_term',
  'create_extension',
  'add_constraint',
  'add_usage_note',
  'no_action',
];
const RQ1_CODEBOOK_SUMMARY = {
  schema_version: 'rq1-codebook-v1',
  valid_requirement_conditions: [
    'Describes catalog, dataset, distribution, data service, or profile metadata rather than internal source content.',
    'Supports discovery, assessment, comparison, access, reuse, or selection.',
    'Can be represented by DCAT/DCAT-AP reuse or a justified profile extension.',
  ],
  exclude_as_not_rq1: [
    'internal_instance_data',
    'per_object_attribute',
    'engineering_calculation',
    'geometry_detail',
    'sensor_measurement_value',
    'ontology_class_mirroring',
    'implementation_detail',
  ],
};
const WORKBENCH_STARTED_AT = new Date().toISOString();
const WORKBENCH_SESSION_ID = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
const WORKBENCH_REVIEWER_ID = window.localStorage.getItem('rqReviewerId') || 'local-reviewer';

export function RequirementWorkbench({ initialView, onStatus }: RequirementWorkbenchProps) {
  const schema = useEditorStore((state) => state.schema);
  const mergeSchema = useEditorStore((state) => state.mergeSchema);
  const [view, setView] = useState<WorkbenchView>(initialView);
  const [sourceCorpusId, setSourceCorpusId] = useState('pilot-corpus');
  const [cqGuided, setCqGuided] = useState(true);
  const [text, setText] = useState(SAMPLE_TEXT);
  const [strategy, setStrategy] = useState<ExtractionStrategy>('rules');
  const [taskText, setTaskText] = useState('');
  const [artifacts, setArtifacts] = useState<ArtifactPayload[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [requirements, setRequirements] = useState<CandidateRequirement[]>([]);
  const [localMergeEvents, setLocalMergeEvents] = useState<Rq1LocalMergeEvent[]>([]);
  const [localSplitEvents, setLocalSplitEvents] = useState<Rq1LocalSplitEvent[]>([]);
  const [selectedRequirementId, setSelectedRequirementId] = useState<string | null>(null);
  const [mergeSelection, setMergeSelection] = useState<Record<string, boolean>>({});
  const [statusFilter, setStatusFilter] = useState<'all' | RequirementStatus>('all');
  const [typeFilter, setTypeFilter] = useState<'all' | RequirementType>('all');
  const [validationFilter, setValidationFilter] = useState<'all' | ValidationStatus>('all');
  const [scopeFilter, setScopeFilter] = useState<'all' | RequirementScope>('all');
  const [recommendations, setRecommendations] = useState<ReuseRecommendation[]>([]);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [shacl, setShacl] = useState('');
  const [generatedProfile, setGeneratedProfile] = useState<SchemaModel | null>(null);
  const [profileChanges, setProfileChanges] = useState<ProfileChangeSet | null>(null);
  const [profileMode, setProfileMode] = useState<ProfileGenerationMode>('minimal');
  const [validationNotes, setValidationNotes] = useState<string[]>([]);
  const [draggingArtifacts, setDraggingArtifacts] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setView(initialView);
  }, [initialView]);

  useEffect(() => {
    if (!analysis) return;
    setRequirements(analysis.requirements);
    setLocalMergeEvents([]);
    setLocalSplitEvents([]);
    setSelectedRequirementId((current) => current ?? analysis.requirements[0]?.id ?? null);
    setMergeSelection({});
    setProfileChanges(null);
    setValidationNotes([]);
  }, [analysis]);

  const userTasks = useMemo<UserTask[]>(
    () =>
      taskText
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line && !line.startsWith('#'))
        .map((statement, index) => ({
          id: `task-${index + 1}`,
          statement,
          kind: statement.endsWith('?') ? ('competency_question' as const) : ('user_task' as const),
          source: 'workbench input',
        })),
    [taskText],
  );

  const requestPayload = useMemo<AnalysisRequest>(
    () => ({ source_corpus_id: sourceCorpusId, text, artifacts, strategy, user_tasks: userTasks, cq_guided: cqGuided }),
    [artifacts, cqGuided, sourceCorpusId, strategy, text, userTasks],
  );

  const filteredRequirements = useMemo(
    () =>
      requirements.filter((requirement) => {
        if (statusFilter !== 'all' && requirement.status !== statusFilter) return false;
        if (typeFilter !== 'all' && requirement.requirement_type !== typeFilter) return false;
        if (validationFilter !== 'all' && requirement.validation_status !== validationFilter) return false;
        if (scopeFilter !== 'all' && requirement.requirement_scope !== scopeFilter) return false;
        return true;
      }),
    [requirements, scopeFilter, statusFilter, typeFilter, validationFilter],
  );

  const selectedRequirement = useMemo(
    () => requirements.find((requirement) => requirement.id === selectedRequirementId) ?? requirements[0] ?? null,
    [requirements, selectedRequirementId],
  );

  const approvedRequirements = useMemo(() => requirements.filter((requirement) => requirement.status === 'approved'), [requirements]);
  const acceptedRecommendationIds = useMemo(
    () => recommendations.filter((recommendation) => accepted[recommendation.id] !== false).map((recommendation) => recommendation.id),
    [accepted, recommendations],
  );

  const runAnalyze = useCallback(async () => {
    setBusy(true);
    onStatus('Analyzing artifacts into evidence units...');
    try {
      const result = await analyzeArtifacts(requestPayload);
      setAnalysis(result);
      setRecommendations([]);
      setShacl('');
      setGeneratedProfile(null);
      onStatus(`Analyzed ${result.evidence_units.length} evidence unit(s) and ${result.requirements.length} candidate requirement(s) [${result.strategy} strategy].`);
      return result;
    } catch (error) {
      onStatus(`Requirement analysis failed: ${error instanceof Error ? error.message : 'unknown error'}`);
      throw error;
    } finally {
      setBusy(false);
    }
  }, [onStatus, requestPayload]);

  const runExtract = useCallback(async () => {
    setBusy(true);
    setView('requirements');
    onStatus('Extracting traceable requirement candidates...');
    try {
      const result = await extractRequirements(requestPayload);
      setAnalysis(result);
      setRecommendations([]);
      setShacl('');
      setGeneratedProfile(null);
      onStatus(`Extracted ${result.requirements.length} requirement candidate(s) from ${result.evidence_units.length} evidence unit(s) [${result.strategy} strategy].`);
      return result;
    } catch (error) {
      onStatus(`Requirement extraction failed: ${error instanceof Error ? error.message : 'unknown error'}`);
      throw error;
    } finally {
      setBusy(false);
    }
  }, [onStatus, requestPayload]);

  const runRecommend = useCallback(async () => {
    setBusy(true);
    setView('reuse');
    onStatus('Preparing reuse recommendations from approved requirements...');
    try {
      const currentAnalysis = analysis ?? (await extractRequirements(requestPayload));
      const reviewed = withRequirements(currentAnalysis, requirements.length ? requirements : currentAnalysis.requirements);
      const approved = reviewed.requirements.filter((requirement) => requirement.status === 'approved');
      if (!approved.length) {
        onStatus('Approve at least one requirement before sending it to reuse recommendation.');
        setView('requirements');
        return [];
      }
      const result = await recommendReuse(withRequirements(reviewed, approved));
      setRecommendations(result.recommendations);
      setAccepted(Object.fromEntries(result.recommendations.map((recommendation) => [recommendation.id, true])));
      onStatus(`Prepared ${result.recommendations.length} reuse recommendation(s) from ${approved.length} approved requirement(s).`);
      return result.recommendations;
    } catch (error) {
      onStatus(`Reuse recommendation failed: ${error instanceof Error ? error.message : 'unknown error'}`);
      throw error;
    } finally {
      setBusy(false);
    }
  }, [analysis, onStatus, requestPayload, requirements]);

  const runProfileChanges = useCallback(async (modeOverride?: ProfileGenerationMode) => {
    // RQ2 step 1: approved requirements -> reviewable profile change proposals.
    const mode = modeOverride ?? profileMode;
    const approved = requirements.filter((requirement) => requirement.status === 'approved');
    if (!approved.length) {
      onStatus('Approve at least one requirement before generating profile changes (RQ2 consumes approved requirements only).');
      setView('requirements');
      return;
    }
    setBusy(true);
    setView('changes');
    onStatus(
      mode === 'minimal'
        ? 'Generating a minimal set of primary profile actions from approved requirements...'
        : 'Generating all candidate profile actions (exploratory mode)...',
    );
    try {
      const result = await generateProfileChanges({ requirements, approved_only: true, mode });
      setProfileChanges(result);
      setShacl('');
      setGeneratedProfile(null);
      setValidationNotes([]);
      const needsReview = result.changes.filter((change) => change.review_status === 'needs_review').length;
      const discovered = Number(result.summary_metrics.discovered_candidate_term_count ?? 0);
      onStatus(
        `Generated ${result.changes.length} ${mode === 'minimal' ? 'primary' : 'candidate'} profile change(s) ` +
          `from ${approved.length} approved requirement(s) (${discovered} candidate term(s) discovered)` +
          (needsReview ? ` - ${needsReview} need(s) review.` : '.'),
      );
    } catch (error) {
      onStatus(`Profile change generation failed: ${error instanceof Error ? error.message : 'unknown error'}`);
      throw error;
    } finally {
      setBusy(false);
    }
  }, [onStatus, profileMode, requirements]);

  const runGenerateDraft = useCallback(async () => {
    // RQ2 step 2: accepted profile changes -> LinkML draft + SHACL (review before merging).
    if (!profileChanges) return;
    setBusy(true);
    onStatus('Generating LinkML profile draft and SHACL from accepted profile changes...');
    try {
      const result = await generateProfileDraft({ profile_change_set: profileChanges, accepted_only: true, base_schema: schema });
      setShacl(result.shacl);
      setGeneratedProfile(result.profile_draft);
      setValidationNotes(result.validation_notes);
      setView('constraints');
      onStatus('Generated profile draft and SHACL. Review them, then merge into the editor explicitly.');
    } catch (error) {
      onStatus(`Profile draft generation failed: ${error instanceof Error ? error.message : 'unknown error'}`);
      throw error;
    } finally {
      setBusy(false);
    }
  }, [onStatus, profileChanges, schema]);

  const runExportRq2 = useCallback(async () => {
    if (!profileChanges) return;
    setBusy(true);
    onStatus('Exporting RQ2 profile generation package...');
    try {
      const approvedCount = requirements.filter((requirement) => requirement.status === 'approved').length;
      const pkg = await exportRq2Package({
        profile_change_set: profileChanges,
        base_schema: schema,
        approved_requirement_count: approvedCount,
        accepted_only: true,
      });
      downloadText(JSON.stringify(pkg, null, 2), 'rq2-profile-package.json', 'application/json');
      onStatus('Exported RQ2 package (change set, LinkML draft, SHACL, provenance mapping).');
    } catch (error) {
      onStatus(`RQ2 export failed: ${error instanceof Error ? error.message : 'unknown error'}`);
      throw error;
    } finally {
      setBusy(false);
    }
  }, [onStatus, profileChanges, requirements, schema]);

  const updateProfileChange = useCallback((id: string, reviewStatus: 'candidate' | 'accepted' | 'rejected' | 'needs_review') => {
    setProfileChanges((current) =>
      current
        ? {
            ...current,
            changes: current.changes.map((change) => (change.id === id ? { ...change, review_status: reviewStatus } : change)),
            review_history: [
              ...(current.review_history ?? []),
              {
                timestamp: new Date().toISOString(),
                reviewer_id: WORKBENCH_REVIEWER_ID,
                session_id: WORKBENCH_SESSION_ID,
                action:
                  reviewStatus === 'accepted'
                    ? 'accept_profile_change'
                    : reviewStatus === 'rejected'
                      ? 'reject_profile_change'
                      : reviewStatus === 'needs_review'
                        ? 'mark_profile_change_needs_review'
                        : 'edit_profile_change_review_status',
                profile_change_id: id,
                old_status: current.changes.find((change) => change.id === id)?.review_status ?? null,
                new_status: reviewStatus,
              },
            ],
          }
        : current,
    );
  }, []);

  const importFiles = useCallback(async (files: FileList | File[] | null) => {
    if (!files?.length) return;
    const loaded = await Promise.all(Array.from(files).map(fileToArtifact));
    setArtifacts((current) => [...current, ...loaded]);
    onStatus(`Loaded ${loaded.length} artifact file(s) for requirement extraction.`);
  }, [onStatus]);

  const onDropArtifacts = useCallback(
    async (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      event.stopPropagation();
      setDraggingArtifacts(false);
      await importFiles(event.dataTransfer.files);
    },
    [importFiles],
  );

  const updateRequirement = useCallback((id: string, patch: Partial<CandidateRequirement>) => {
    setRequirements((current) => current.map((requirement) => (requirement.id === id ? applyRequirementPatch(requirement, patch) : requirement)));
  }, []);

  const updateIntent = useCallback((id: string, patch: Partial<NormalizedIntent>) => {
    setRequirements((current) =>
      current.map((requirement) =>
        requirement.id === id ? applyIntentPatch(requirement, patch) : requirement,
      ),
    );
  }, []);

  const exportRq1Dataset = useCallback(() => {
    if (!analysis) {
      onStatus('Run extraction before exporting an RQ1 dataset.');
      return;
    }
    const dataset = buildRq1DatasetExport(analysis, requirements, localMergeEvents, localSplitEvents);
    downloadText(JSON.stringify(dataset, null, 2), 'rq1-requirement-dataset.json', 'application/json');
    onStatus(`Exported RQ1 dataset with ${requirements.length} reviewed requirement(s).`);
  }, [analysis, localMergeEvents, localSplitEvents, onStatus, requirements]);

  const mergeRequirements = useCallback((ids: string[], suggestedStatement?: string) => {
    const selected = requirements.filter((requirement) => ids.includes(requirement.id));
    if (selected.length < 2) {
      onStatus('Select at least two requirements to merge.');
      return;
    }
    const base = selected[0];
    const statement = suggestedStatement || selected.map(requirementStatement).join(' ');
    const timestamp = new Date().toISOString();
    const merged: CandidateRequirement = {
      ...base,
      id: `req-merged-${Date.now()}`,
      raw_statement: selected.map(requirementStatement).join(' / '),
      normalized_statement: statement,
      title: 'Merged requirement',
      description: statement,
      status: 'candidate',
      review_notes: 'Merged locally in the Requirement Workbench.',
      merged_from: selected.map((requirement) => requirement.id),
      source_evidence: uniqueEvidence(selected.flatMap((requirement) => requirement.source_evidence)),
      evidence: uniqueStrings(selected.flatMap((requirement) => requirement.evidence)),
      confidence: Math.max(...selected.map((requirement) => requirement.confidence)),
    };
    setRequirements((current) =>
      current.map((requirement): CandidateRequirement => (ids.includes(requirement.id) ? applyRequirementPatch(requirement, { status: 'merged' }) : requirement)).concat(merged),
    );
    setLocalMergeEvents((current) => [
      ...current,
      {
        timestamp,
        source_requirement_ids: selected.map((requirement) => requirement.id),
        merged_requirement_id: merged.id,
        normalized_statement: statement,
        suggested_statement_used: Boolean(suggestedStatement),
      },
    ]);
    setSelectedRequirementId(merged.id);
    setMergeSelection({});
    onStatus(`Merged ${selected.length} requirement candidates for review.`);
  }, [onStatus, requirements]);

  const splitRequirement = useCallback(() => {
    if (!selectedRequirement) return;
    const textToSplit = requirementStatement(selectedRequirement);
    const pieces = textToSplit.split(/\s+and\s+|;/i).map((part) => part.trim()).filter(Boolean);
    const parts = pieces.length > 1 ? pieces.slice(0, 2) : [textToSplit, `${textToSplit} (additional review item)`];
    const timestamp = new Date().toISOString();
    const splitToken = Date.now();
    const splitItems = parts.map((part, index): CandidateRequirement => ({
      ...selectedRequirement,
      id: `${selectedRequirement.id}-split-${index + 1}-${splitToken}`,
      raw_statement: selectedRequirement.raw_statement,
      normalized_statement: part,
      title: `${selectedRequirement.title || 'Requirement'} split ${index + 1}`,
      description: part,
      status: 'needs_review',
      review_notes: `Split from ${selectedRequirement.id}.`,
      merged_from: [selectedRequirement.id],
    }));
    setRequirements((current) =>
      current
        .map((requirement): CandidateRequirement => (requirement.id === selectedRequirement.id ? applyRequirementPatch(requirement, { status: 'merged' }) : requirement))
        .concat(splitItems),
    );
    setLocalSplitEvents((current) => [
      ...current,
      {
        timestamp,
        source_requirement_id: selectedRequirement.id,
        split_requirement_ids: splitItems.map((requirement) => requirement.id),
        source_statement: textToSplit,
      },
    ]);
    setSelectedRequirementId(splitItems[0].id);
    onStatus('Split the selected requirement into review items.');
  }, [onStatus, selectedRequirement]);

  function mergeDraft() {
    if (!generatedProfile) return;
    if (validationNotes.some((note) => note.includes('not present in the supplied base schema'))) {
      onStatus('Generated draft references a base class missing from the active editor schema. Resolve the validation note before merging.');
      return;
    }
    mergeSchema(generatedProfile);
    onStatus('Merged generated requirement profile draft into the visual editor. Review before saving.');
  }

  return (
    <main className="requirement-workbench">
      <WorkflowGuide analysis={analysis} profileChanges={profileChanges} view={view} />
      <section
        className={`requirement-input-panel ${draggingArtifacts ? 'requirement-input-panel--dragging' : ''}`}
        onDragEnter={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setDraggingArtifacts(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          event.stopPropagation();
          if (event.currentTarget === event.target) setDraggingArtifacts(false);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = 'copy';
        }}
        onDrop={(event) => void onDropArtifacts(event)}
      >
        <div className="requirement-input-panel__header">
          <div>
            <h2>Requirement Workbench</h2>
            <p>Extract evidence-backed profile requirements without changing the visual schema canvas.</p>
          </div>
          <label className="file-picker">
            <FileSearch size={16} />
            Add files
            <input accept={ARTIFACT_ACCEPT} multiple onChange={(event) => void importFiles(event.target.files)} type="file" />
          </label>
        </div>

        <div className="artifact-drop-zone">
          <FileSearch size={18} />
          <span>Drop artifacts</span>
          <small>Text, AAS JSON, AASX, DCAT/RDF, IFC</small>
        </div>

        <div className="study-setup-grid">
          <label>
            Source corpus ID
            <input onChange={(event) => setSourceCorpusId(event.target.value)} value={sourceCorpusId} />
          </label>
          <label className="toggle-row">
            <input checked={cqGuided} onChange={(event) => setCqGuided(event.target.checked)} type="checkbox" />
            CQ-guided extraction
          </label>
        </div>

        <div className="input-boundary-note">
          <strong>Extraction input</strong>
          <span>source documents, competency questions, and user tasks</span>
          <strong>Held out</strong>
          <span>expert reference requirements, expected answer sets, and manually curated gold requirements</span>
        </div>

        <textarea aria-label="Requirement text" className="requirement-textarea" onChange={(event) => setText(event.target.value)} value={text} />

        <textarea
          aria-label="Competency questions and user tasks"
          className="requirement-textarea requirement-textarea--tasks"
          onChange={(event) => setTaskText(event.target.value)}
          placeholder={'Competency questions / user tasks (one per line), e.g.\nWhich datasets describe HVAC equipment in building X?'}
          rows={3}
          value={taskText}
        />

        <label className="requirement-strategy">
          Extraction strategy
          <select onChange={(event) => setStrategy(event.target.value as ExtractionStrategy)} value={strategy}>
            <option value="rules">Rule-based (baseline)</option>
            <option value="llm">LLM-assisted (verified evidence)</option>
            <option value="hybrid">Hybrid (LLM + rules)</option>
          </select>
        </label>

        {artifacts.length ? (
          <div className="artifact-list">
            {artifacts.map((artifact) => (
              <span key={`${artifact.name}-${artifact.content.length}`}>{artifact.name}</span>
            ))}
          </div>
        ) : null}

        <div className="requirement-actions">
          <button disabled={busy} onClick={() => void runAnalyze()} type="button">
            <Search size={16} />
            Analyze
          </button>
          <button disabled={busy} onClick={() => void runExtract()} type="button">
            <CheckCircle2 size={16} />
            Extract
          </button>
          <button disabled={busy} onClick={() => void runRecommend()} type="button">
            <RefreshCw size={16} />
            Recommend
          </button>
          <button className="primary" disabled={busy} onClick={() => void runProfileChanges()} title="RQ2: generate reviewable profile change proposals from approved requirements" type="button">
            <Wand2 size={16} />
            Profile changes
          </button>
        </div>
      </section>

      <section className="requirement-review-panel">
        <div className="workflow-tabs">
          {[
            ['requirements', 'Requirement Review'],
            ['reuse', 'Reuse'],
            ['changes', 'Profile Changes'],
            ['constraints', 'Generated Profile'],
          ].map(([id, label]) => (
            <button className={view === id ? 'active' : undefined} key={id} onClick={() => setView(id as WorkbenchView)} type="button">
              {label}
            </button>
          ))}
        </div>

        {view === 'requirements' ? (
          <RequirementReview
            analysis={analysis}
            filteredRequirements={filteredRequirements}
            mergeRequirements={mergeRequirements}
            mergeSelection={mergeSelection}
            requirements={requirements}
            selectedRequirement={selectedRequirement}
            setMergeSelection={setMergeSelection}
            setSelectedRequirementId={setSelectedRequirementId}
            setScopeFilter={setScopeFilter}
            setStatusFilter={setStatusFilter}
            setTypeFilter={setTypeFilter}
            setValidationFilter={setValidationFilter}
            scopeFilter={scopeFilter}
            splitRequirement={splitRequirement}
            statusFilter={statusFilter}
            typeFilter={typeFilter}
            updateIntent={updateIntent}
            updateRequirement={updateRequirement}
            validationFilter={validationFilter}
            onExportRq1Dataset={exportRq1Dataset}
          />
        ) : view === 'reuse' ? (
          <ReuseResults accepted={accepted} recommendations={recommendations} setAccepted={setAccepted} />
        ) : view === 'changes' ? (
          <ProfileChangesView
            approvedCount={requirements.filter((requirement) => requirement.status === 'approved').length}
            busy={busy}
            changeSet={profileChanges}
            mode={profileMode}
            onChangeMode={(nextMode) => {
              setProfileMode(nextMode);
              void runProfileChanges(nextMode);
            }}
            onExportRq2={() => void runExportRq2()}
            onGenerateDraft={() => void runGenerateDraft()}
            updateProfileChange={updateProfileChange}
          />
        ) : (
          <section className="constraint-preview">
            <div className="constraint-preview__actions">
              <button disabled={!shacl} onClick={() => downloadText(shacl, 'requirement-profile.shacl.ttl', 'text/turtle')} type="button">
                <FileCode size={16} />
                SHACL
              </button>
              <button
                disabled={!generatedProfile}
                onClick={() => generatedProfile && downloadText(JSON.stringify(generatedProfile, null, 2), 'generated-profile.linkml.json', 'application/json')}
                type="button"
              >
                <Download size={16} />
                LinkML
              </button>
              <button disabled={!generatedProfile || validationNotes.some((note) => note.includes('not present in the supplied base schema'))} onClick={mergeDraft} type="button">
                <GitMerge size={16} />
                Merge Draft
              </button>
            </div>
            {validationNotes.length ? (
              <ul className="validation-notes">
                {validationNotes.map((note) => (
                  <li key={note}>
                    <AlertTriangle size={13} /> {note}
                  </li>
                ))}
              </ul>
            ) : null}
            <pre>{shacl || 'Generate a profile draft from accepted profile changes to preview SHACL and LinkML output.'}</pre>
          </section>
        )}
      </section>
    </main>
  );
}

function WorkflowGuide({
  analysis,
  profileChanges,
  view,
}: {
  analysis: AnalysisResponse | null;
  profileChanges: ProfileChangeSet | null;
  view: WorkbenchView;
}) {
  const activeStep = view === 'reuse' ? 3 : view === 'changes' ? 4 : view === 'constraints' ? 5 : analysis ? 3 : 1;
  const steps = [
    {
      step: 1,
      title: 'Sources & Questions',
      user: 'Load source documents, CQs, and user tasks.',
      system: 'Stores the study setup and extraction boundary.',
      export: 'Source corpus id and CQ-guided flag.',
    },
    {
      step: 2,
      title: 'Extract & Abstract',
      user: 'Run rules, LLM, or hybrid extraction.',
      system: 'Evidence units, source signals, grouped discovery needs, and candidate requirements.',
      export: 'Evidence units, warnings, and funnel metrics.',
    },
    {
      step: 3,
      title: 'Review Requirements',
      user: 'Approve, reject, edit, merge, or split catalog-level requirements.',
      system: 'Reviewed RQ1 state with editor history.',
      export: 'Reviewed RQ1 dataset.',
    },
    {
      step: 4,
      title: 'Anchor Changes',
      user: 'Generate minimal profile-change proposals from approved requirements.',
      system: 'RQ2 seam: selected changes plus candidate terms as suggestions.',
      export: 'ProfileChangeSet and decision log.',
    },
    {
      step: 5,
      title: 'Validate & Export',
      user: 'Accept changes and generate LinkML, SHACL, and packages.',
      system: 'Checks active base schema before merge.',
      export: 'RQ2 package, LinkML draft, SHACL, metrics.',
    },
  ];
  const candidateTerms = Number(profileChanges?.summary_metrics.discovered_candidate_term_count ?? 0);
  const selectedChanges = Number(profileChanges?.summary_metrics.selected_profile_change_count ?? 0);
  const reduction = Number(profileChanges?.summary_metrics.reduction_rate ?? 0);

  return (
    <section className="guided-workflow-shell" aria-label="Guided RQ1 RQ2 workflow">
      <div className="guided-workflow-shell__header">
        <div>
          <h2>Guided RQ1/RQ2 Profile Workbench</h2>
          <p>Catalog-level discovery requirements become a minimal, reviewed set of profile changes.</p>
        </div>
        <div className="guided-workflow-shell__metrics">
          <span>Candidate terms discovered: <strong>{candidateTerms}</strong></span>
          <span>Selected profile changes: <strong>{selectedChanges}</strong></span>
          <span>Reduction: <strong>{Math.round(reduction * 100)}%</strong></span>
        </div>
      </div>
      <div className="workflow-step-grid">
        {steps.map((step) => (
          <article className={step.step === activeStep ? 'is-active' : ''} key={step.step}>
            <span>{step.step}</span>
            <h3>{step.title}</h3>
            <p><strong>User</strong>{step.user}</p>
            <p><strong>System</strong>{step.system}</p>
            <small>{step.export}</small>
          </article>
        ))}
      </div>
      <p className="candidate-term-note">Candidate terms are suggestions, not review items. Minimal mode remains the default RQ2 path.</p>
    </section>
  );
}

function RequirementReview({
  analysis,
  filteredRequirements,
  mergeRequirements,
  mergeSelection,
  requirements,
  selectedRequirement,
  setMergeSelection,
  setSelectedRequirementId,
  setScopeFilter,
  setStatusFilter,
  setTypeFilter,
  setValidationFilter,
  scopeFilter,
  splitRequirement,
  statusFilter,
  typeFilter,
  updateIntent,
  updateRequirement,
  validationFilter,
  onExportRq1Dataset,
}: {
  analysis: AnalysisResponse | null;
  filteredRequirements: CandidateRequirement[];
  mergeRequirements: (ids: string[], suggestedStatement?: string) => void;
  mergeSelection: Record<string, boolean>;
  requirements: CandidateRequirement[];
  selectedRequirement: CandidateRequirement | null;
  setMergeSelection: (selection: Record<string, boolean>) => void;
  setSelectedRequirementId: (id: string) => void;
  setScopeFilter: (scope: 'all' | RequirementScope) => void;
  setStatusFilter: (status: 'all' | RequirementStatus) => void;
  setTypeFilter: (type: 'all' | RequirementType) => void;
  setValidationFilter: (status: 'all' | ValidationStatus) => void;
  scopeFilter: 'all' | RequirementScope;
  splitRequirement: () => void;
  statusFilter: 'all' | RequirementStatus;
  typeFilter: 'all' | RequirementType;
  updateIntent: (id: string, patch: Partial<NormalizedIntent>) => void;
  updateRequirement: (id: string, patch: Partial<CandidateRequirement>) => void;
  validationFilter: 'all' | ValidationStatus;
  onExportRq1Dataset: () => void;
}) {
  if (!analysis) {
    return <EmptyState text="Run Extract to build evidence units and reviewable requirement records." />;
  }

  const selectedMergeIds = Object.entries(mergeSelection).filter(([, checked]) => checked).map(([id]) => id);

  return (
    <div className="review-workspace">
      <ReviewOverview analysis={analysis} requirements={requirements} />
      <FunnelMetrics metrics={analysis.funnel_metrics} />
      <Rq1CodebookPanel />
      <ValidationWarnings requirements={requirements} />
      <div className="requirement-review-grid">
        <section className="requirement-list-panel">
          <div className="panel-title-row">
            <div>
              <h3>Requirement Queue</h3>
              <small>{filteredRequirements.length} shown</small>
            </div>
            <button onClick={onExportRq1Dataset} type="button">
              <Download size={16} />
              Export RQ1 Dataset
            </button>
          </div>
          <div className="requirement-filters">
            <label>
              Status
              <select onChange={(event) => setStatusFilter(event.target.value as 'all' | RequirementStatus)} value={statusFilter}>
                <option value="all">All</option>
                {STATUS_OPTIONS.map((status) => (
                  <option key={status} value={status}>{humanize(status)}</option>
                ))}
              </select>
            </label>
            <label>
              Type
              <select onChange={(event) => setTypeFilter(event.target.value as 'all' | RequirementType)} value={typeFilter}>
                <option value="all">All</option>
                {REQUIREMENT_TYPES.map((type) => (
                  <option key={type} value={type}>{humanize(type)}</option>
                ))}
              </select>
            </label>
            <label>
              Validation
              <select onChange={(event) => setValidationFilter(event.target.value as 'all' | ValidationStatus)} value={validationFilter}>
                <option value="all">All</option>
                {VALIDATION_STATUS_OPTIONS.map((status) => (
                  <option key={status} value={status}>{humanize(status)}</option>
                ))}
              </select>
            </label>
            <label>
              Scope
              <select onChange={(event) => setScopeFilter(event.target.value as 'all' | RequirementScope)} value={scopeFilter}>
                <option value="all">All</option>
                {REQUIREMENT_SCOPE_OPTIONS.map((scope) => (
                  <option key={scope} value={scope}>{humanize(scope)}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="review-list">
            {filteredRequirements.map((requirement, index) => (
              <article className={`review-list-item ${selectedRequirement?.id === requirement.id ? 'active' : ''}`} key={requirement.id}>
                <label className="merge-checkbox" title="Select for merge">
                  <input
                    checked={mergeSelection[requirement.id] === true}
                    onChange={(event) => setMergeSelection({ ...mergeSelection, [requirement.id]: event.target.checked })}
                    type="checkbox"
                  />
                </label>
                <button onClick={() => setSelectedRequirementId(requirement.id)} type="button">
                  <span className="queue-index">{index + 1}</span>
                  <strong>{shortStatement(requirement)}</strong>
                  <span>{humanize(requirement.requirement_type)} - {formatConfidence(requirement.confidence)}</span>
                  <RequirementMetaStrip requirement={requirement} />
                  <small className={`status-pill status-pill--${requirement.status}`}>{humanize(requirement.status)}</small>
                </button>
              </article>
            ))}
          </div>

          <div className="merge-actions">
            <button disabled={selectedMergeIds.length < 2} onClick={() => mergeRequirements(selectedMergeIds)} type="button">
              <GitMerge size={16} />
              Merge selected
            </button>
          </div>
        </section>

        <RequirementDetail
          analysis={analysis}
          mergeRequirements={mergeRequirements}
          requirement={selectedRequirement}
          requirements={requirements}
          splitRequirement={splitRequirement}
          updateIntent={updateIntent}
          updateRequirement={updateRequirement}
        />
      </div>
    </div>
  );
}

function ReviewOverview({ analysis, requirements }: { analysis: AnalysisResponse; requirements: CandidateRequirement[] }) {
  const approved = requirements.filter((requirement) => requirement.status === 'approved').length;
  const needsReview = requirements.filter((requirement) => requirement.status === 'needs_review').length;
  const rejected = requirements.filter((requirement) => requirement.status === 'rejected').length;

  return (
    <section className="review-overview" aria-label="Requirement review overview">
      <div>
        <h3>Review extracted requirements</h3>
        <p>Evidence-backed extraction results. Approved items feed reuse recommendation; other statuses remain in review.</p>
      </div>
      <div className="review-overview__stats">
        <span><strong>{requirements.length}</strong> total</span>
        <span><strong>{approved}</strong> approved</span>
        <span><strong>{needsReview}</strong> needs review</span>
        <span><strong>{rejected}</strong> rejected</span>
        <span><strong>{analysis.evidence_units.length}</strong> evidence</span>
        <span><strong>{analysis.duplicate_groups.length}</strong> duplicate hints</span>
      </div>
    </section>
  );
}

function FunnelMetrics({ metrics }: { metrics: Record<string, unknown> }) {
  const metric = (key: string) => Number(metrics[key] ?? 0);
  return (
    <section className="funnel-metrics" aria-label="Extraction funnel metrics">
      <span><strong>{metric('evidence_unit_count')}</strong> evidence units</span>
      <span><strong>{metric('source_signal_count')}</strong> source signals</span>
      <span><strong>{metric('candidate_requirement_count')}</strong> candidate requirements</span>
      <span><strong>{metric('discarded_domain_content_count')}</strong> discarded domain-content signals</span>
      <span><strong>{metric('merged_duplicate_count')}</strong> duplicate reductions</span>
    </section>
  );
}

function Rq1CodebookPanel() {
  return (
    <details className="rq1-codebook-panel">
      <summary>What counts as an RQ1 requirement?</summary>
      <div>
        <p>Valid RQ1 candidates describe catalog/dataset/distribution metadata, support discovery or assessment tasks, and can be represented by DCAT/DCAT-AP reuse or a justified extension.</p>
        <ul>
          <li>Good: dataset exposes represented asset/entity types for discovery.</li>
          <li>Exclude: {RQ1_CODEBOOK_SUMMARY.exclude_as_not_rq1.map(humanize).join(', ')}.</li>
          <li>Held out: expert reference requirements and expected answer sets stay out of extraction and belong in validation.</li>
        </ul>
      </div>
    </details>
  );
}

function ValidationWarnings({ requirements }: { requirements: CandidateRequirement[] }) {
  const warnings = requirements.filter((requirement) => requirement.validation_status !== 'valid');
  if (!warnings.length) return null;

  return (
    <section className="validation-warning-panel" aria-label="Validation warnings">
      <div>
        <h3>Validation warnings</h3>
        <p>{warnings.length} requirement(s) need machine-validation review before RQ1 export.</p>
      </div>
      <div className="validation-warning-list">
        {warnings.map((requirement) => (
          <article key={requirement.id}>
            <strong>{shortStatement(requirement)}</strong>
            <span>{humanize(requirement.validation_status)}</span>
          </article>
        ))}
      </div>
    </section>
  );
}

function RequirementMetaStrip({ requirement }: { requirement: CandidateRequirement }) {
  return (
    <span className="requirement-meta-strip">
      <small>{humanize(requirement.validation_status)}</small>
      <small>{humanize(requirement.requirement_scope)}</small>
      <small>{requirement.provenance?.strategy ?? 'unknown strategy'}</small>
      <small>{requirement.provenance?.model_id ?? 'no model'}</small>
      <small>{formatEvidenceVerification(requirement.provenance?.evidence_verified)}</small>
      <small>{requirement.source_evidence.length} evidence</small>
    </span>
  );
}

function RequirementDetail({
  analysis,
  mergeRequirements,
  requirement,
  requirements,
  splitRequirement,
  updateIntent,
  updateRequirement,
}: {
  analysis: AnalysisResponse;
  mergeRequirements: (ids: string[], suggestedStatement?: string) => void;
  requirement: CandidateRequirement | null;
  requirements: CandidateRequirement[];
  splitRequirement: () => void;
  updateIntent: (id: string, patch: Partial<NormalizedIntent>) => void;
  updateRequirement: (id: string, patch: Partial<CandidateRequirement>) => void;
}) {
  if (!requirement) return <section className="requirement-detail-panel"><EmptyState text="Select a requirement to review." /></section>;

  return (
    <section className="requirement-detail-panel">
      <div className="detail-header">
        <div>
          <small>Selected requirement</small>
          <h3>{shortStatement(requirement)}</h3>
          <small>{requirement.id}</small>
        </div>
        <span className={`status-pill status-pill--${requirement.status}`}>{humanize(requirement.status)}</span>
      </div>

      <section className="requirement-machine-metadata" aria-label="Requirement machine metadata">
        <span><strong>Validation</strong>{humanize(requirement.validation_status)}</span>
        <span><strong>Scope</strong>{humanize(requirement.requirement_scope)}</span>
        <span><strong>Strategy</strong>{requirement.provenance?.strategy ?? 'unknown'}</span>
        <span><strong>Model</strong>{requirement.provenance?.model_id ?? 'none'}</span>
        <span><strong>Evidence</strong>{formatEvidenceVerification(requirement.provenance?.evidence_verified)}</span>
        <span><strong>Sources</strong>{requirement.source_evidence.length}</span>
      </section>

      <div className="review-actions review-actions--primary">
        <button onClick={() => updateRequirement(requirement.id, { status: 'approved' })} type="button">
          <CheckCircle2 size={16} />
          Approve
        </button>
        <button onClick={() => updateRequirement(requirement.id, { status: 'needs_review' })} type="button">
          <AlertTriangle size={16} />
          Needs review
        </button>
        <button onClick={() => updateRequirement(requirement.id, { status: 'rejected' })} type="button">
          <XCircle size={16} />
          Reject
        </button>
      </div>

      <label>
        Normalized statement
        <textarea
          className="statement-editor"
          onChange={(event) => updateRequirement(requirement.id, { normalized_statement: event.target.value, description: event.target.value })}
          value={requirement.normalized_statement || ''}
        />
      </label>

      <div className="detail-form-grid">
        <label>
          Requirement type
          <select onChange={(event) => updateRequirement(requirement.id, { requirement_type: event.target.value as RequirementType })} value={requirement.requirement_type}>
            {REQUIREMENT_TYPES.map((type) => <option key={type} value={type}>{humanize(type)}</option>)}
          </select>
        </label>
        <label>
          Requirement scope
          <select onChange={(event) => updateRequirement(requirement.id, { requirement_scope: event.target.value as RequirementScope })} value={requirement.requirement_scope}>
            {REQUIREMENT_SCOPE_OPTIONS.map((scope) => <option key={scope} value={scope}>{humanize(scope)}</option>)}
          </select>
        </label>
        <label>
          Resource type
          <select onChange={(event) => updateIntent(requirement.id, { resource_type: event.target.value as NormalizedIntent['resource_type'] })} value={requirement.normalized_intent.resource_type}>
            {RESOURCE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        <label>
          Value kind
          <select onChange={(event) => updateIntent(requirement.id, { value_kind: event.target.value as NormalizedIntent['value_kind'] })} value={requirement.normalized_intent.value_kind}>
            {VALUE_KINDS.map((kind) => <option key={kind} value={kind}>{humanize(kind)}</option>)}
          </select>
        </label>
        <label>
          Obligation
          <select onChange={(event) => updateIntent(requirement.id, { obligation_hint: event.target.value as NormalizedIntent['obligation_hint'] })} value={requirement.normalized_intent.obligation_hint}>
            {OBLIGATION_HINTS.map((hint) => <option key={hint} value={hint}>{humanize(hint)}</option>)}
          </select>
        </label>
      </div>

      <label>
        Metadata need
        <input onChange={(event) => updateIntent(requirement.id, { metadata_need: event.target.value })} value={requirement.normalized_intent.metadata_need} />
      </label>

      <label>
        Review notes
        <textarea
          onChange={(event) => updateRequirement(requirement.id, { review_notes: event.target.value })}
          value={requirement.review_notes || ''}
        />
      </label>

      <div className="supporting-sections">
        <details open>
          <summary>Evidence for this requirement ({requirement.source_evidence.length})</summary>
          <EvidencePanel requirement={requirement} />
        </details>
        <details>
          <summary>FAIR and metadata actions</summary>
          <FairAndActions requirement={requirement} updateRequirement={updateRequirement} />
        </details>
        <details>
          <summary>Raw extracted statement</summary>
          <label>
            Raw statement
            <textarea
              onChange={(event) => updateRequirement(requirement.id, { raw_statement: event.target.value })}
              value={requirement.raw_statement || ''}
            />
          </label>
        </details>
        <details>
          <summary>Duplicate suggestions ({analysis.duplicate_groups.length})</summary>
          <DuplicatePanel groups={analysis.duplicate_groups} mergeRequirements={mergeRequirements} requirements={requirements} />
        </details>
        <details>
          <summary>Extracted attributes ({analysis.extracted_attributes.length})</summary>
          <ExtractedAttributes attributes={analysis.extracted_attributes} />
        </details>
      </div>

      <div className="review-actions">
        <button onClick={splitRequirement} type="button">
          <SplitSquareHorizontal size={16} />
          Split requirement
        </button>
      </div>
    </section>
  );
}

function FairAndActions({
  requirement,
  updateRequirement,
}: {
  requirement: CandidateRequirement;
  updateRequirement: (id: string, patch: Partial<CandidateRequirement>) => void;
}) {
  function updateAction(index: number, patch: Partial<CandidateMetadataAction>) {
    const next = requirement.candidate_metadata_actions.map((action, actionIndex) =>
      actionIndex === index ? { ...action, ...patch } : action,
    );
    updateRequirement(requirement.id, { candidate_metadata_actions: next });
  }

  function updateConstraint(index: number, patch: Partial<NonNullable<CandidateMetadataAction['constraint_hint']>>) {
    const current = requirement.candidate_metadata_actions[index];
    updateAction(index, {
      constraint_hint: {
        value_kind: current.constraint_hint?.value_kind ?? requirement.normalized_intent.value_kind,
        obligation: current.constraint_hint?.obligation ?? requirement.normalized_intent.obligation_hint,
        ...current.constraint_hint,
        ...patch,
      },
    });
  }

  return (
    <div className="fair-action-panel">
      <div>
        <h4>FAIR dimensions</h4>
        <div className="fair-toggle-group" aria-label="FAIR dimensions">
          {FAIR_DIMENSIONS.map((dimension) => (
            <label key={dimension}>
              <input
                checked={requirement.fair_dimensions.includes(dimension)}
                onChange={(event) => {
                  const current = requirement.fair_dimensions;
                  updateRequirement(requirement.id, {
                    fair_dimensions: event.target.checked ? uniqueStrings([...current, dimension]) as FairDimension[] : current.filter((item) => item !== dimension),
                  });
                }}
                type="checkbox"
              />
              {dimension}
            </label>
          ))}
        </div>
      </div>

      <label>
        FAIR rationale
        <textarea
          onChange={(event) => updateRequirement(requirement.id, { fair_rationale: event.target.value })}
          value={requirement.fair_rationale || ''}
        />
      </label>

      <section className="metadata-action-list">
        <h4>Suggested metadata anchors</h4>
        {requirement.candidate_metadata_actions.map((action, index) => (
          <article key={`${action.action}-${index}`}>
            <details>
              <summary>
                <strong>{humanize(action.action)}</strong>
                <code>{action.candidate_terms.join(', ') || 'no term'}</code>
              </summary>
              <div className="metadata-action-editor">
                <label>
                  Action
                  <select onChange={(event) => updateAction(index, { action: event.target.value as CandidateMetadataAction['action'] })} value={action.action}>
                    {METADATA_ACTIONS.map((item) => <option key={item} value={item}>{humanize(item)}</option>)}
                  </select>
                </label>
                <label>
                  Target class
                  <select onChange={(event) => updateAction(index, { target_class: event.target.value })} value={action.target_class || requirement.normalized_intent.resource_type}>
                    {RESOURCE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                  </select>
                </label>
                <label>
                  Candidate terms
                  <input
                    onChange={(event) => updateAction(index, { candidate_terms: splitTerms(event.target.value) })}
                    value={action.candidate_terms.join(', ')}
                  />
                </label>
                <label>
                  Cardinality
                  <input
                    onChange={(event) => updateConstraint(index, { cardinality: event.target.value || null })}
                    placeholder="0..n"
                    value={action.constraint_hint?.cardinality || ''}
                  />
                </label>
                <label>
                  Constraint value kind
                  <select
                    onChange={(event) => updateConstraint(index, { value_kind: event.target.value as NormalizedIntent['value_kind'] })}
                    value={action.constraint_hint?.value_kind ?? requirement.normalized_intent.value_kind}
                  >
                    {VALUE_KINDS.map((kind) => <option key={kind} value={kind}>{humanize(kind)}</option>)}
                  </select>
                </label>
                <label>
                  Constraint obligation
                  <select
                    onChange={(event) => updateConstraint(index, { obligation: event.target.value as NormalizedIntent['obligation_hint'] })}
                    value={action.constraint_hint?.obligation ?? requirement.normalized_intent.obligation_hint}
                  >
                    {OBLIGATION_HINTS.map((hint) => <option key={hint} value={hint}>{humanize(hint)}</option>)}
                  </select>
                </label>
                <label className="metadata-action-editor__wide">
                  Rationale
                  <textarea onChange={(event) => updateAction(index, { rationale: event.target.value })} value={action.rationale} />
                </label>
              </div>
            </details>
          </article>
        ))}
      </section>
    </div>
  );
}

function EvidencePanel({ requirement }: { requirement: CandidateRequirement | null }) {
  if (!requirement) return null;

  return (
    <section className="evidence-section">
      <h3>Source Evidence</h3>
      {requirement.source_evidence.length ? (
        <div className="evidence-list">
          {requirement.source_evidence.map((evidence) => (
            <article className="evidence-item" key={evidence.evidence_unit_id}>
              <small>{evidence.artifact_name} - {evidence.artifact_kind}</small>
              {evidence.locator ? <code>{evidence.locator}</code> : null}
              <p>{evidence.evidence_text}</p>
              {evidence.extracted_facts.length ? <ul>{evidence.extracted_facts.map((fact) => <li key={fact}>{fact}</li>)}</ul> : null}
            </article>
          ))}
        </div>
      ) : (
        <EmptyState text="No source evidence is attached to this requirement." />
      )}
    </section>
  );
}

function DuplicatePanel({
  groups,
  mergeRequirements,
  requirements,
}: {
  groups: AnalysisResponse['duplicate_groups'];
  mergeRequirements: (ids: string[], suggestedStatement?: string) => void;
  requirements: CandidateRequirement[];
}) {
  if (!groups.length) return null;
  const byId = Object.fromEntries(requirements.map((requirement) => [requirement.id, requirement]));

  return (
    <section className="duplicate-section">
      <h3>Duplicate Suggestions</h3>
      {groups.map((group) => (
        <article className="duplicate-group" key={group.id}>
          <strong>{group.id}</strong>
          <p>{group.reason}</p>
          <code>{group.suggested_merged_statement}</code>
          <ul>
            {group.requirement_ids.map((id) => (
              <li key={id}>{byId[id]?.title || byId[id]?.normalized_statement || id}</li>
            ))}
          </ul>
          <div className="review-actions">
            <button onClick={() => mergeRequirements(group.requirement_ids, group.suggested_merged_statement)} type="button">
              <GitMerge size={16} />
              Merge
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}

async function fileToArtifact(file: File): Promise<ArtifactPayload> {
  if (/\.aasx$/i.test(file.name)) {
    return {
      name: file.name,
      media_type: file.type || 'application/asset-administration-shell-package',
      content: arrayBufferToBase64(await file.arrayBuffer()),
      content_encoding: 'base64',
    };
  }

  return {
    name: file.name,
    media_type: file.type || undefined,
    content: await file.text(),
    content_encoding: 'text',
  };
}

function arrayBufferToBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return window.btoa(binary);
}

function ExtractedAttributes({ attributes }: { attributes: ExtractedAttribute[] }) {
  if (!attributes.length) return null;

  return (
    <section className="result-section">
      <h3>Extracted Attributes</h3>
      <div className="attribute-table" role="table" aria-label="Extracted artifact attributes">
        <div className="attribute-table__header" role="row">
          <span>Attribute</span>
          <span>Value</span>
          <span>Path</span>
          <span>Source</span>
        </div>
        {attributes.map((attribute) => (
          <article className="attribute-row" key={attribute.id} role="row">
            <span>
              <strong>{attribute.label}</strong>
              <small>{attribute.category}</small>
            </span>
            <code>{attribute.value || 'empty'}</code>
            <code>{attribute.path}</code>
            <small>{attribute.source}</small>
          </article>
        ))}
      </div>
    </section>
  );
}

function ReuseResults({
  accepted,
  recommendations,
  setAccepted,
}: {
  accepted: Record<string, boolean>;
  recommendations: ReuseRecommendation[];
  setAccepted: (accepted: Record<string, boolean>) => void;
}) {
  if (!recommendations.length) {
    return <EmptyState text="Approve requirements, then run reuse recommendation to map them to reusable terms." />;
  }

  return (
    <div className="candidate-list">
      {recommendations.map((recommendation) => (
        <article className="recommendation-item" key={recommendation.id}>
          <label className="recommendation-toggle">
            <input
              checked={accepted[recommendation.id] !== false}
              onChange={(event) => setAccepted({ ...accepted, [recommendation.id]: event.target.checked })}
              type="checkbox"
            />
            <span>{recommendation.label}</span>
          </label>
          <code>{recommendation.term_uri}</code>
          <p>{recommendation.rationale}</p>
          <small>
            {recommendation.vocabulary} - priority {recommendation.priority} - {recommendation.action} - {formatConfidence(recommendation.confidence)}
          </small>
        </article>
      ))}
    </div>
  );
}

function SummaryStrip({ analysis, requirements }: { analysis: AnalysisResponse; requirements: CandidateRequirement[] }) {
  const approved = requirements.filter((requirement) => requirement.status === 'approved').length;
  return (
    <div className="summary-strip">
      <span>{analysis.artifacts.length} artifacts</span>
      <span>{analysis.evidence_units.length} evidence units</span>
      <span>{requirements.length} requirements</span>
      <span>{approved} approved</span>
      <span>{analysis.duplicate_groups.length} duplicate groups</span>
    </div>
  );
}

function ProfileChangesView({
  approvedCount,
  busy,
  changeSet,
  mode,
  onChangeMode,
  onExportRq2,
  onGenerateDraft,
  updateProfileChange,
}: {
  approvedCount: number;
  busy: boolean;
  changeSet: ProfileChangeSet | null;
  mode: ProfileGenerationMode;
  onChangeMode: (mode: ProfileGenerationMode) => void;
  onExportRq2: () => void;
  onGenerateDraft: () => void;
  updateProfileChange: (id: string, reviewStatus: 'candidate' | 'accepted' | 'rejected' | 'needs_review') => void;
}) {
  if (!changeSet) {
    return (
      <EmptyState text="Approve requirements in Requirement Review, then click 'Profile changes' to generate reviewable DCAT-AP profile change proposals (RQ2)." />
    );
  }

  const acceptedCount = changeSet.changes.filter((change) => change.review_status === 'accepted').length;
  const needsReviewCount = changeSet.changes.filter((change) => change.review_status === 'needs_review').length;
  const metrics = changeSet.summary_metrics;
  const metric = (key: string) => Number(metrics[key] ?? 0);
  const percent = (key: string) => `${Math.round(metric(key) * 100)}%`;

  return (
    <section className="profile-changes-view">
      <div className="review-overview">
        <div>
          <h3>Review proposed profile changes</h3>
          <p>
            RQ2 seam: approved RQ1 requirements become minimal profile-change proposals. Generated from {approvedCount} approved requirement(s) against the {changeSet.profile_base} base. Accept or reject each change; the
            LinkML draft and SHACL are generated from accepted changes only.
          </p>
        </div>
        <div className="review-overview__stats">
          <span><strong>{changeSet.changes.length}</strong> {mode === 'minimal' ? 'primary' : 'candidate'}</span>
          <span><strong>{acceptedCount}</strong> accepted</span>
          <span><strong>{needsReviewCount}</strong> needs review</span>
        </div>
      </div>

      <div className="profile-mode-toggle" role="radiogroup" aria-label="Profile generation mode">
        <button
          aria-pressed={mode === 'minimal'}
          className={mode === 'minimal' ? 'is-active' : ''}
          disabled={busy}
          onClick={() => mode !== 'minimal' && onChangeMode('minimal')}
          type="button"
        >
          Minimal profile
          <small>One primary, reuse-first action per requirement (default)</small>
        </button>
        <button
          aria-pressed={mode === 'exploratory'}
          className={mode === 'exploratory' ? 'is-active' : ''}
          disabled={busy}
          onClick={() => mode !== 'exploratory' && onChangeMode('exploratory')}
          type="button"
        >
          Exploratory
          <small>Show every candidate action (debugging / full recall)</small>
        </button>
      </div>

      <dl className="profile-metrics" aria-label="Minimal-profile metrics">
        <div><dt>Candidate terms</dt><dd>{metric('discovered_candidate_term_count')}</dd></div>
        <div><dt>Selected changes</dt><dd>{metric('selected_profile_change_count')}</dd></div>
        <div><dt>Reduction</dt><dd>{percent('reduction_rate')}</dd></div>
        <div><dt>Reuse</dt><dd>{percent('reuse_rate')}</dd></div>
        <div><dt>Extension</dt><dd>{percent('extension_rate')}</dd></div>
        <div><dt>Requirements addressed</dt><dd>{metric('requirements_addressed_count')}</dd></div>
        <div><dt>Avg changes / requirement</dt><dd>{metric('average_profile_changes_per_requirement')}</dd></div>
      </dl>

      {changeSet.warnings.length ? (
        <ul className="validation-notes" aria-label="Profile change warnings">
          {changeSet.warnings.map((warning) => (
            <li key={warning}>
              <AlertTriangle size={13} /> {warning}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="candidate-list">
        {changeSet.changes.map((change) => (
          <article className={`profile-change-item profile-change-item--${change.review_status}`} key={change.id}>
            <div className="profile-change-item__header">
              <strong>{humanize(change.change_type)}</strong>
              <span className={`status-pill status-pill--${change.review_status === 'accepted' ? 'approved' : change.review_status}`}>
                {humanize(change.review_status)}
              </span>
            </div>
            <code>
              {change.target_class} . {change.slot_name || change.class_name || '?'}
              {change.range ? ` : ${change.range}` : ''}
            </code>
            <small>
              {change.source_vocabulary || 'unknown vocabulary'} - {change.obligation_level}
              {change.required ? ' - required' : ''}
              {change.multivalued ? ' - multivalued' : ''} - from {change.source_requirement_ids.join(', ')} - {change.evidence_ids.length} evidence ref(s)
            </small>
            <p>{change.rationale}</p>
            {change.alternative_terms && change.alternative_terms.length ? (
              <details className="candidate-suggestions">
                <summary>{change.alternative_terms.length} other candidate term(s) considered</summary>
                <ul>
                  {change.alternative_terms.map((term) => (
                    <li key={term}><code>{term}</code></li>
                  ))}
                </ul>
              </details>
            ) : null}
            {change.warnings.length ? (
              <ul className="validation-notes">
                {change.warnings.map((warning) => (
                  <li key={warning}>
                    <AlertTriangle size={13} /> {warning}
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="review-actions">
              <button onClick={() => updateProfileChange(change.id, 'accepted')} type="button">
                <CheckCircle2 size={16} />
                Accept
              </button>
              <button onClick={() => updateProfileChange(change.id, 'rejected')} type="button">
                <XCircle size={16} />
                Reject
              </button>
            </div>
          </article>
        ))}
      </div>

      {changeSet.discovered_candidate_terms.length ? (
        <details className="candidate-suggestions candidate-suggestions--all">
          <summary>{changeSet.discovered_candidate_terms.length} candidate term(s) discovered (suggestions, not review items)</summary>
          <ul>
            {changeSet.discovered_candidate_terms.map((term) => (
              <li key={term}><code>{term}</code></li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="constraint-preview__actions">
        <button className="primary" disabled={busy || acceptedCount === 0} onClick={onGenerateDraft} type="button">
          <Wand2 size={16} />
          Generate draft + SHACL from accepted changes
        </button>
        <button disabled={busy} onClick={onExportRq2} type="button">
          <Download size={16} />
          Export RQ2 package
        </button>
      </div>
    </section>
  );
}

function EmptyState({ text }: { text: string }) {
  return <p className="empty-state">{text}</p>;
}

function withRequirements(analysis: AnalysisResponse, requirements: CandidateRequirement[]): AnalysisResponse {
  return { ...analysis, requirements };
}

function applyRequirementPatch(requirement: CandidateRequirement, patch: Partial<CandidateRequirement>): CandidateRequirement {
  const updated = { ...requirement, ...patch };
  const fields: Array<keyof CandidateRequirement> = [
    'normalized_statement',
    'requirement_type',
    'requirement_scope',
    'candidate_metadata_actions',
    'fair_dimensions',
    'review_notes',
    'status',
  ];
  const history = fields
    .filter((field) => field in patch && !sameHistoryValue(requirement[field], patch[field]))
    .map((field) =>
      editorHistoryEntry(
        String(field),
        requirement[field],
        patch[field],
        field === 'status'
          ? actionForStatusChange(patch.status)
          : field === 'candidate_metadata_actions'
            ? 'edit_candidate_metadata_action'
            : 'edit',
      ),
    );
  return history.length ? { ...updated, provenance: appendEditorHistory(requirement.provenance, history) } : updated;
}

function applyIntentPatch(requirement: CandidateRequirement, patch: Partial<NormalizedIntent>): CandidateRequirement {
  const updatedIntent = { ...requirement.normalized_intent, ...patch };
  const fields: Array<keyof NormalizedIntent> = ['metadata_need', 'resource_type', 'value_kind', 'obligation_hint'];
  const history = fields
    .filter((field) => field in patch && !sameHistoryValue(requirement.normalized_intent[field], patch[field]))
    .map((field) => editorHistoryEntry(String(field), requirement.normalized_intent[field], patch[field], 'edit'));
  const updated = { ...requirement, normalized_intent: updatedIntent };
  return history.length ? { ...updated, provenance: appendEditorHistory(requirement.provenance, history) } : updated;
}

function appendEditorHistory(provenance: ExtractionProvenance | null | undefined, entries: Array<Record<string, unknown>>): ExtractionProvenance {
  const base: ExtractionProvenance = provenance ?? {
    strategy: 'rules',
    extractor: 'frontend-review',
    notes: [],
    editor_history: [],
  };
  return {
    ...base,
    notes: base.notes ?? [],
    editor_history: [...(base.editor_history ?? []), ...entries],
  };
}

function editorHistoryEntry(field: string, oldValue: unknown, newValue: unknown, action: EditorHistoryAction) {
  return {
    timestamp: new Date().toISOString(),
    reviewer_id: WORKBENCH_REVIEWER_ID,
    session_id: WORKBENCH_SESSION_ID,
    field,
    old_value: oldValue ?? null,
    new_value: newValue ?? null,
    action,
  };
}

function actionForStatusChange(status: RequirementStatus | undefined): EditorHistoryAction {
  if (status === 'approved') return 'approve';
  if (status === 'rejected') return 'reject';
  if (status === 'needs_review') return 'mark_needs_review';
  return 'edit';
}

function sameHistoryValue(left: unknown, right: unknown) {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

function buildRq1DatasetExport(
  analysis: AnalysisResponse,
  requirements: CandidateRequirement[],
  localMergeEvents: Rq1LocalMergeEvent[],
  localSplitEvents: Rq1LocalSplitEvent[],
): Rq1DatasetExport {
  return {
    schema_version: 'rq1-requirement-dataset-v1',
    export_kind: 'reviewed_frontend_state',
    generated_at: new Date().toISOString(),
    source_corpus_id: analysis.study_setup?.source_corpus_id as string | null | undefined,
    reviewer_id: WORKBENCH_REVIEWER_ID,
    session_id: WORKBENCH_SESSION_ID,
    started_at: WORKBENCH_STARTED_AT,
    completed_at: new Date().toISOString(),
    duration_ms: Date.now() - Date.parse(WORKBENCH_STARTED_AT),
    study_setup: analysis.study_setup,
    rq1_codebook: RQ1_CODEBOOK_SUMMARY,
    strategy_requested: analysis.strategy,
    strategy_used: analysis.strategy,
    summary_metrics: {
      requirement_count: requirements.length,
      funnel_metrics: analysis.funnel_metrics,
      evidence_unit_count: analysis.evidence_units.length,
      duplicate_group_count: analysis.duplicate_groups.length,
      user_task_count: analysis.user_tasks.length,
      warning_count: analysis.warnings.length,
      requirements_by_type: countBy(requirements, (requirement) => requirement.requirement_type),
      requirements_by_scope: countBy(requirements, (requirement) => requirement.requirement_scope),
      requirements_by_validation_status: countBy(requirements, (requirement) => requirement.validation_status),
      requirements_by_review_status: countBy(requirements, (requirement) => requirement.status),
      requirements_with_editor_history: requirements.filter((requirement) => requirement.provenance?.editor_history?.length).length,
      requirements_approved_with_valid_validation: requirements.filter(
        (requirement) => requirement.status === 'approved' && requirement.validation_status === 'valid',
      ).length,
      requirements_approved_with_warnings: requirements.filter(
        (requirement) => requirement.status === 'approved' && requirement.validation_status !== 'valid',
      ).length,
      local_merge_event_count: localMergeEvents.length,
      local_split_event_count: localSplitEvents.length,
      competency_question_coverage: buildCqCoverage(requirements, analysis.user_tasks),
    },
    requirements,
    evidence_units: analysis.evidence_units,
    duplicate_groups: analysis.duplicate_groups,
    duplicate_groups_original: analysis.duplicate_groups,
    local_merge_events: localMergeEvents,
    local_split_events: localSplitEvents,
    user_tasks: analysis.user_tasks,
    funnel_metrics: analysis.funnel_metrics,
    warnings: analysis.warnings,
    review_editor_history: requirements.map((requirement) => ({
      requirement_id: requirement.id,
      review_status: requirement.status,
      validation_status: requirement.validation_status,
      review_notes: requirement.review_notes ?? null,
      editor_history: requirement.provenance?.editor_history ?? [],
    })),
  };
}

function buildCqCoverage(requirements: CandidateRequirement[], userTasks: UserTask[]) {
  const active = requirements.filter((requirement) => requirement.status !== 'rejected' && requirement.status !== 'merged');
  const covered = new Set(active.flatMap((requirement) => requirement.supports_user_tasks));
  return {
    task_count: userTasks.length,
    covered_task_count: userTasks.filter((task) => covered.has(task.id)).length,
    uncovered_task_ids: userTasks.filter((task) => !covered.has(task.id)).map((task) => task.id),
    requirements_without_task_links: active.filter((requirement) => !requirement.supports_user_tasks.length).map((requirement) => requirement.id),
  };
}

function countBy<T>(items: T[], getKey: (item: T) => string) {
  return items.reduce<Record<string, number>>((counts, item) => {
    const key = getKey(item);
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});
}

function formatEvidenceVerification(value: boolean | null | undefined) {
  if (value === true) return 'evidence verified';
  if (value === false) return 'evidence unverified';
  return 'evidence unknown';
}

function requirementStatement(requirement: CandidateRequirement) {
  return requirement.normalized_statement || requirement.description || requirement.raw_statement || requirement.title || requirement.id;
}

function shortStatement(requirement: CandidateRequirement) {
  const statement = requirementStatement(requirement);
  return statement.length > 72 ? `${statement.slice(0, 69)}...` : statement;
}

function uniqueEvidence(items: SourceEvidence[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${item.evidence_unit_id}:${item.locator || ''}:${item.evidence_text}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function uniqueStrings<T extends string>(items: T[]) {
  return Array.from(new Set(items.filter(Boolean)));
}

function splitTerms(value: string) {
  return value.split(/[\s,]+/).map((term) => term.trim()).filter(Boolean);
}

function humanize(value: string) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatConfidence(confidence: number) {
  return `${Math.round(confidence * 100)}%`;
}
