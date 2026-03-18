#!/usr/bin/env sh
set -eu
mkdir -p /app/generated/jsonschema /app/generated/shacl
python -m linkml.generators.jsonschemagen /app/schemas/construct_dcat.yaml > /app/generated/jsonschema/construct_dcat.schema.json
python -m linkml.generators.shaclgen /app/schemas/construct_dcat.yaml > /app/generated/shacl/construct_dcat.shacl.ttl
