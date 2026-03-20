from __future__ import annotations
from fastapi.staticfiles import StaticFiles

import json
import yaml
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jsonschema import Draft202012Validator
from rdflib import Graph, Literal, Namespace, RDF, URIRef

BASE_DIR = Path('/app') if Path('/app').exists() else Path(__file__).resolve().parents[2]
SCHEMA_PATH = BASE_DIR / 'generated' / 'jsonschema' / 'construct_dcat.schema.json'
EXAMPLE_PATH = BASE_DIR / 'examples' / 'dataset_minimal.json'

DCAT = Namespace('http://www.w3.org/ns/dcat#')
DCT = Namespace('http://purl.org/dc/terms/')
CX = Namespace('https://example.org/construct-dcat/')

app = FastAPI(title='Construct-DCAT Starter')
app.mount('/static', StaticFiles(directory=str(Path(__file__).parent / 'static')), name='static')
templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))


def load_schema() -> dict[str, Any]:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f'Missing generated schema: {SCHEMA_PATH}')
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def get_validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


def payload_to_graph(data: dict[str, Any]) -> Graph:
    g = Graph()
    g.bind('dcat', DCAT)
    g.bind('dct', DCT)
    g.bind('cx', CX)

    dataset_uri = URIRef(f"https://example.org/dataset/{data['identifier']}")
    g.add((dataset_uri, RDF.type, DCAT.Dataset))
    g.add((dataset_uri, DCT.identifier, Literal(data['identifier'])))
    g.add((dataset_uri, DCT.title, Literal(data['title'])))

    if data.get('description'):
        g.add((dataset_uri, DCT.description, Literal(data['description'])))

    for kw in data.get('keyword', []):
        g.add((dataset_uri, DCAT.keyword, Literal(kw)))

    if data.get('asset_kind'):
        g.add((dataset_uri, CX.assetKind, Literal(data['asset_kind'])))
    if data.get('lifecycle_phase'):
        g.add((dataset_uri, CX.lifecyclePhase, Literal(data['lifecycle_phase'])))
    if data.get('bim_model_ref'):
        g.add((dataset_uri, CX.bimModelReference, URIRef(data['bim_model_ref'])))
    if data.get('aas_ref'):
        g.add((dataset_uri, CX.aasReference, URIRef(data['aas_ref'])))
    if data.get('geometry_format'):
        g.add((dataset_uri, CX.geometryFormat, Literal(data['geometry_format'])))
    if data.get('contact_point'):
        g.add((dataset_uri, DCAT.contactPoint, Literal(data['contact_point'])))

    for i, dist in enumerate(data.get('distribution', []), start=1):
        dist_uri = URIRef(f"{dataset_uri}/distribution/{i}")
        g.add((dist_uri, RDF.type, DCAT.Distribution))
        g.add((dataset_uri, DCAT.distribution, dist_uri))
        if dist.get('access_url'):
            g.add((dist_uri, DCAT.accessURL, URIRef(dist['access_url'])))
        if dist.get('download_url'):
            g.add((dist_uri, DCAT.downloadURL, URIRef(dist['download_url'])))
        if dist.get('media_type'):
            g.add((dist_uri, DCAT.mediaType, Literal(dist['media_type'])))
        if dist.get('format'):
            g.add((dist_uri, DCT.format, Literal(dist['format'])))

    return g


@app.get('/', response_class=HTMLResponse)
def index(request: Request):
    example = {}
    if EXAMPLE_PATH.exists():
        example = json.loads(EXAMPLE_PATH.read_text(encoding='utf-8'))
    return templates.TemplateResponse('index.html', {'request': request, 'example': example})


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/schema')
def schema() -> JSONResponse:
    return JSONResponse(load_schema())


@app.post('/validate')
def validate(payload: dict[str, Any]) -> JSONResponse:
    validator = get_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        return JSONResponse(
            status_code=422,
            content={
                'valid': False,
                'errors': [
                    {
                        'path': '.'.join(str(x) for x in err.path),
                        'message': err.message,
                    }
                    for err in errors
                ],
            },
        )
    return JSONResponse({'valid': True, 'errors': []})


@app.post('/export/jsonld')
def export_jsonld(payload: dict[str, Any]) -> JSONResponse:
    validator = get_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        raise HTTPException(status_code=422, detail='Payload failed validation')
    g = payload_to_graph(payload)
    return JSONResponse(json.loads(g.serialize(format='json-ld', indent=2)))


@app.post('/export/turtle')
def export_turtle(payload: dict[str, Any]) -> PlainTextResponse:
    validator = get_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        raise HTTPException(status_code=422, detail='Payload failed validation')
    g = payload_to_graph(payload)
    ttl = g.serialize(format='turtle')
    return PlainTextResponse(ttl, media_type='text/turtle')

@app.get("/schema/uml")
def get_uml():
    base_path = BASE_DIR / "schemas" / "dcat_ap_base.yaml"
    ext_path = BASE_DIR / "schemas" / "construct_dcat.yaml"

    with open(base_path, encoding="utf-8") as f:
        base_schema = yaml.safe_load(f)

    with open(ext_path, encoding="utf-8") as f:
        ext_schema = yaml.safe_load(f)

    classes = {}
    classes.update(base_schema.get("classes", {}))
    classes.update(ext_schema.get("classes", {}))

    slots = {}
    slots.update(base_schema.get("slots", {}))
    slots.update(ext_schema.get("slots", {}))

    enums = {}
    enums.update(base_schema.get("enums", {}))
    enums.update(ext_schema.get("enums", {}))

    def safe_slot_label(slot_name: str, slot_def: dict) -> str:
        slot_uri = slot_def.get("slot_uri", "")
        if ":" in slot_uri:
            prefix, local = slot_uri.split(":", 1)
            return f"{local} ({prefix})"
        return slot_name

    uml = "classDiagram\n"

    for cls, content in classes.items():
        uml += f"  class {cls} {{\n"

        all_slots = list(content.get("slots", []))
        parent = content.get("is_a")
        if parent and parent in classes:
            all_slots = list(classes[parent].get("slots", [])) + all_slots

        for slot_name in all_slots:
            slot_def = slots.get(slot_name, {})
            slot_label = safe_slot_label(slot_name, slot_def)
            slot_range = slot_def.get("range", "string")

            required = slot_def.get("required", False)
            multivalued = slot_def.get("multivalued", False)

            if required and multivalued:
                card = "[1..*]"
            elif required:
                card = "[1]"
            elif multivalued:
                card = "[*]"
            else:
                card = "[0..1]"

            enum = enums.get(slot_range)
            if enum:
                values = ",".join(enum.get("permissible_values", {}).keys())
                uml += f"    {slot_label} : {slot_range} {card} [{values}]\n"
            else:
                uml += f"    {slot_label} : {slot_range} {card}\n"

        uml += "  }\n"

    for cls, content in classes.items():
        all_slots = list(content.get("slots", []))

        parent = content.get("is_a")
        if parent and parent in classes:
            all_slots = list(classes[parent].get("slots", [])) + all_slots
            uml += f"  {cls} --|> {parent}\n"

        for slot_name in all_slots:
            slot_def = slots.get(slot_name, {})
            slot_label = safe_slot_label(slot_name, slot_def)
            slot_range = slot_def.get("range")

            if slot_range in classes:
                uml += f"  {cls} --> {slot_range} : {slot_label}\n"

    return {"mermaid": uml}

@app.post("/schema/add-slot")
def add_slot(payload: dict):
    schema_path = BASE_DIR / "schemas" / "construct_dcat.yaml"

    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    class_name = payload["class_name"]
    slot_name = payload["slot_name"]
    slot_type = payload["slot_type"]

    # add slot definition
    schema.setdefault("slots", {})[slot_name] = {
        "range": slot_type
    }

    # add slot to class
    schema["classes"][class_name].setdefault("slots", []).append(slot_name)

    # save back
    with open(schema_path, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, sort_keys=False)

    return {"status": "ok"}

@app.post("/schema/add-enum-value")
def add_enum_value(payload: dict):
    schema_path = BASE_DIR / "schemas" / "construct_dcat.yaml"

    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    enum_name = payload["enum_name"]
    value = payload["value"]

    enums = schema.setdefault("enums", {})

    if enum_name not in enums:
        enums[enum_name] = {"permissible_values": {}}

    enums[enum_name].setdefault("permissible_values", {})[value] = None

    with open(schema_path, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, sort_keys=False)

    return {"status": "ok"}

@app.post("/schema/delete-slot")
def delete_slot(payload: dict):
    schema_path = BASE_DIR / "schemas" / "construct_dcat.yaml"

    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    class_name = payload["class_name"]
    slot_name = payload["slot_name"]

    class_slots = schema.get("classes", {}).get(class_name, {}).get("slots", [])
    if slot_name in class_slots:
        class_slots.remove(slot_name)

    # remove global slot definition too, if present
    if slot_name in schema.get("slots", {}):
        del schema["slots"][slot_name]

    with open(schema_path, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, sort_keys=False)

    return {"status": "ok"}

@app.post("/schema/delete-enum-value")
def delete_enum_value(payload: dict):
    schema_path = BASE_DIR / "schemas" / "construct_dcat.yaml"

    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    enum_name = payload["enum_name"]
    value = payload["value"]

    enums = schema.get("enums", {})
    if enum_name in enums:
        permissible = enums[enum_name].get("permissible_values", {})
        if value in permissible:
            del permissible[value]

    with open(schema_path, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, sort_keys=False)

    return {"status": "ok"}

@app.post("/schema/update-slot-flags")
def update_slot_flags(payload: dict):
    schema_path = BASE_DIR / "schemas" / "construct_dcat.yaml"

    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    slot_name = payload["slot_name"]
    required = payload.get("required", False)
    multivalued = payload.get("multivalued", False)

    slot_def = schema.setdefault("slots", {}).setdefault(slot_name, {})
    slot_def["required"] = required
    slot_def["multivalued"] = multivalued

    with open(schema_path, "w", encoding="utf-8") as f:
        yaml.dump(schema, f, sort_keys=False)

    return {"status": "ok"}

