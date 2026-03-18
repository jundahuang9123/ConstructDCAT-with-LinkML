FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app
COPY scripts /app/scripts
COPY schemas /app/schemas
RUN chmod +x /app/scripts/generate.sh && mkdir -p /app/generated/jsonschema /app/generated/shacl

EXPOSE 8000
