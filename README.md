# Visual Profile Editor

A visual semantic application profile editor for extending DCAT/DCAT-AP with construction-domain metadata constraints using LinkML, SHACL, JSON Schema, and RDF.

## Introduction

![Construct-DCAT visual profile editor showing DCAT/DCAT-AP base classes with selected construction-domain dataset extensions](docs/assets/construct-dcat-profile-editor-demo.png)

The editor supports reuse-first profile engineering: users start from DCAT/DCAT-AP classes, add Construct-DCAT constraints, inspect semantic anchors and dataset extensions such as AAS and BIM datasets, and export profile artifacts from the same visual model.

This repository is a specialized profile-editor application built from the generic [`General-Ontology-Editor`](https://github.com/jundahuang9123/General-Ontology-Editor). The general editor provides the reusable visual schema/ontology editing foundation, while this repository specializes the workflow for Construct-DCAT and construction-domain dataset discovery.

The tool is designed for metadata interoperability workflows where users need to reuse, constrain, and extend existing vocabularies such as DCAT, DCAT-AP, DCTERMS, SKOS, PROV, AAS, IFC/BOT, and construction-domain vocabularies.

Instead of functioning as a full OWL ontology engineering environment, this application focuses on practical semantic profile development: visual class/property profile editing, cardinality and requirement constraints, LinkML source generation, SHACL validation export, JSON Schema generation, RDF/Turtle export, and profile package generation.

Typical use cases include:

- creating a DCAT-compatible construction-domain metadata profile;
- extending DCAT/DCAT-AP for AAS, BIM, RDF/OWL, IFC, tabular, and hybrid construction datasets;
- defining reusable metadata constraints for dataspace onboarding;
- adding semantic anchors from datasets to ontologies, SKOS concepts, AAS submodels, IFC entities, and controlled vocabularies;
- importing existing RDF/OWL/SHACL/LinkML resources and turning them into editable profile models;
- exporting SHACL, JSON Schema, LinkML, and RDF artifacts from one visual model.

## Repository Relationship

`Visual Profile Editor` depends on the reusable Python backend/core package from `General-Ontology-Editor`. Construct-DCAT-specific templates, validation rules, examples, terminology, frontend workflow, and export packaging live in this repository only.

## Start The App

```bash
docker compose up --build
```

Then open:

- Profile editor: `http://localhost:8080/`
- API docs: `http://localhost:8080/docs`
- Health: `http://localhost:8080/health`

## Profile Workflow

1. Select a base profile template.
2. Reuse and constrain DCAT/DCAT-AP terms.
3. Add construction-domain semantic anchors.
4. Validate the profile model.
5. Export SHACL, JSON Schema, RDF, LinkML, or a complete Construct-DCAT profile package.

## Useful Endpoints

- `GET /api/profile/model`
- `GET /api/profile/workspace`
- `PUT /api/profile/workspace`
- `GET /api/profile/templates`
- `POST /api/profile/templates/{template_id}/load`
- `POST /api/profile/validate`
- `GET /profile/export/package`
- `GET /profile/export/shacl`
- `GET /profile/export/rdf`

The legacy dataset onboarding demo routes remain available:

- `POST /validate`
- `POST /export/jsonld`
- `POST /export/turtle`

## Project Structure

```text
visual-profile-editor/
  backend/      FastAPI app and Construct-DCAT profile routes
  frontend/     React + TypeScript profile editor UI
  profiles/     profile templates and example metadata
  schemas/      versioned default profile seeds
  .vpe-workspace/ ignored local active profile storage
  scripts/      artifact generation
  generated/    generated JSON Schema and SHACL files
```

## Active Profile Storage

The editor keeps the active working profile in an ignored local workspace, not
in `schemas/profile.yaml`. By default it writes `.vpe-workspace/profiles/profile.yaml`;
set `VPE_PROFILE_WORKSPACE` or use the start dialog's active schema folder field
to choose another local directory. Versioned files in `schemas/` remain default
starting points for fresh workspaces and tests.

## Requirement Extraction & Reuse Recommendation

The workbench includes a separate `requirement-reuse-service` container for semi-automated, reuse-first profile engineering from heterogeneous artifacts.

Initial supported inputs:

- textual requirements and competency questions;
- AAS JSON and `.aasx` packages with submodels, semantic IDs, concept descriptions, and `idShort` patterns;
- existing DCAT/RDF/JSON-LD metadata examples;
- lightweight IFC snippets for schema, class, and property-set discovery.

The frontend exposes workflow tabs for profile editing, requirement extraction, reuse recommendations, validation, and export. Requirement results are always reviewable: users accept or reject recommendations before generating SHACL/profile drafts.

**RQ1 — extraction.** Three strategies: a deterministic rule-based baseline, an LLM-assisted strategy with evidence-unit verification, and a hybrid of both. The LLM layer is provider-agnostic (disabled by default, Anthropic native, or any OpenAI-compatible endpoint such as Ollama, vLLM, OpenRouter). Requirements are represented as traceable records (source evidence, user-task links, FAIR relevance, candidate reuse terms, validation status, extraction provenance incl. reviewer edit history) defined normatively in LinkML and persisted as YAML requirement sets. See [docs/requirement-extraction.md](docs/requirement-extraction.md).

**RQ2 — profile generation.** Approved requirements (only) are converted into a reviewable `ProfileChangeSet`; accepted changes generate a DCAT-AP-based LinkML profile draft and SHACL shapes, with provenance from every generated element back to requirement and evidence ids, exported as a reproducibility package and merged into the visual editor only on explicit user action. See [docs/profile-generation.md](docs/profile-generation.md).

Service endpoints are proxied through the main app under:

- `POST /api/requirements/analyze-artifacts`
- `POST /api/requirements/extract-requirements`
- `POST /api/requirements/export-rq1-dataset`
- `POST /api/requirements/recommend-reuse`
- `POST /api/requirements/generate-profile-changes`
- `POST /api/requirements/generate-profile-draft`
- `POST /api/requirements/generate-shacl-from-profile-changes`
- `POST /api/requirements/export-rq2-package`
- `POST /api/requirements/generate-shacl` (legacy)
- `POST /api/requirements/save-requirement-set`
- `POST /api/requirements/list-requirement-sets`
- `POST /api/requirements/load-requirement-set`

The service itself remains independently deployable on port `8010`. Evaluation tooling: `scripts/extract_requirements.py` (corpus runs) and `scripts/evaluate_rq1.py` (strategy comparison incl. gold matching and review-effort metrics), with example corpus, gold set, and export artifacts under `examples/`.

## Developer Dependency Note

For normal VPE setup, install the backend requirements:

```bash
python -m pip install -r backend/requirements.txt
```

That file already pins the GOE backend package to a GitHub tag, so a sibling `../General-Ontology-Editor` checkout is not required.

If you are actively changing the GOE Python core and want VPE to use your local checkout temporarily:

```bash
python -m pip install -r backend/requirements.txt
python -m pip install -e ../General-Ontology-Editor
```

When GOE changes should become the default for VPE, create a new GOE tag and update the pinned dependency in `backend/requirements.txt`.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
