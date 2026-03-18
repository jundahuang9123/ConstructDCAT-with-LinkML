# Construct-DCAT Docker Starter

A Docker-first starter project for a construction-domain DCAT extension backed by LinkML, FastAPI, and a no-build web UI.

## Stack
- LinkML schema in `schemas/construct_dcat.yaml`
- FastAPI backend in `backend/`
- Plain HTML/CSS/JS frontend served by FastAPI (no npm required)
- Docker Compose for local development

## Quick start

```bash
docker compose up --build
```

Then open:
- Web UI: http://localhost:8000/
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## What it does
- Lets users fill in a simple Construct-DCAT onboarding form
- Validates JSON against the generated JSON Schema
- Exports JSON-LD and Turtle
- Keeps the schema as the single source of truth

## Generate artifacts locally

```bash
docker compose run --rm generator
```

Generated files go to:
- `generated/jsonschema/construct_dcat.schema.json`
- `generated/shacl/construct_dcat.shacl.ttl`

## Project structure

```text
construct-dcat-docker/
  backend/
  schemas/
  scripts/
  examples/
  generated/
  docker-compose.yml
```

## Notes
- This is a starter scaffold, not a production deployment.
- The frontend is intentionally simple and does not require npm.
- The LinkML schema is a thin Construct-DCAT profile over DCAT-style metadata.
