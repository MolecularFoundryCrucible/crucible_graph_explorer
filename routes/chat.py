import json
import os

import anthropic
import requests as _requests

_anthropic_kwargs = {}
if os.getenv("ANTHROPIC_BASE_URL"):
    _anthropic_kwargs["base_url"] = os.getenv("ANTHROPIC_BASE_URL")
if os.getenv("ANTHROPIC_AUTH_TOKEN"):
    _anthropic_kwargs["auth_token"] = os.getenv("ANTHROPIC_AUTH_TOKEN")
else:
    _anthropic_kwargs["api_key"] = os.getenv("ANTHROPIC_API_KEY", "not-required")

anthropic_client = anthropic.Anthropic(**_anthropic_kwargs)

from flask import (
    Blueprint, abort, current_app, render_template,
    request, Response, session, stream_with_context,
)
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client

CHAT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

CHAT_TOOL_DEFS = [
    {
        "name": "get_sample",
        "description": "Retrieve full details for a single sample by its unique ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sample_id": {"type": "string", "description": "The unique_id of the sample"}
            },
            "required": ["sample_id"]
        }
    },
    {
        "name": "get_dataset",
        "description": "Retrieve full details (including scientific metadata) for a dataset by its unique ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "The unique_id of the dataset"}
            },
            "required": ["dataset_id"]
        }
    },
    {
        "name": "search_samples",
        "description": "Search samples in the project by name substring.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring to match against sample names"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_datasets",
        "description": "Search datasets in the project by name or measurement type substring.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring to match against dataset names or measurement types"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_samples_for_dataset",
        "description": "List all samples associated with a given dataset.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "The unique_id of the dataset"}
            },
            "required": ["dataset_id"]
        }
    },
    {
        "name": "get_entity_graph",
        "description": (
            "Return the lineage graph for a sample or dataset: its ancestor and descendant samples, "
            "sample-to-sample relationships, and the datasets associated with each sample. "
            "Use this to understand provenance, processing history, or what measurements exist for a sample."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string", "enum": ["sample", "dataset"],
                                "description": "Whether the ID refers to a sample or a dataset"},
                "entity_id":   {"type": "string", "description": "The unique_id of the sample or dataset"}
            },
            "required": ["entity_type", "entity_id"]
        }
    },
    {
        "name": "get_thumbnail",
        "description": "Retrieve and display a thumbnail image for a dataset. Use this when the user asks to see an image, photo, or thumbnail of a dataset.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "The unique_id of the dataset"}
            },
            "required": ["dataset_id"]
        }
    },
]


_FULL_LIST_THRESHOLD = 150


def _grouped_summary(items, name_key, type_key, examples=3):
    """Return grouped-by-type summary lines with a few name examples per group."""
    groups = {}
    for it in items:
        t = it.get(type_key) or 'unknown'
        groups.setdefault(t, []).append(it)
    lines = []
    for t, members in sorted(groups.items()):
        ex = ', '.join(m[name_key] for m in members[:examples])
        suffix = f' (e.g. {ex})' if ex else ''
        lines.append(f"- {t}: {len(members)}{suffix}")
    return '\n'.join(lines)


def build_system_prompt(pc):
    project_id = pc['project_id']
    samples = pc.get('samples', [])
    datasets = pc.get('datasets', [])

    if len(samples) <= _FULL_LIST_THRESHOLD:
        sample_section = '\n'.join(
            f"- {s['sample_name']} ({s.get('sample_type', 'unknown')}) [{s['unique_id']}]"
            for s in samples
        )
        sample_note = ''
    else:
        sample_section = _grouped_summary(samples, 'sample_name', 'sample_type')
        sample_note = '\nUse search_samples(query) to locate specific samples by name.'

    if len(datasets) <= _FULL_LIST_THRESHOLD:
        dataset_section = '\n'.join(
            f"- {d['dataset_name']} ({d.get('measurement', 'unknown')}) [{d['unique_id']}]"
            for d in datasets
        )
        dataset_note = ''
    else:
        dataset_section = _grouped_summary(datasets, 'dataset_name', 'measurement')
        dataset_note = '\nUse search_datasets(query) to locate specific datasets by name or measurement type.'

    return f"""You are a scientific data assistant for Crucible project '{project_id}'.

## Samples ({len(samples)} total)
{sample_section}{sample_note}

## Datasets ({len(datasets)} total)
{dataset_section}{dataset_note}

Use the provided tools to retrieve scientific metadata, sample details, and dataset details \
when answering questions. Always cite the IDs of the samples or datasets you reference."""


def execute_chat_tool(name, inputs, crucible_client, pc, get_entity_graph_nx):
    try:
        if name == 'get_sample':
            result = crucible_client.samples.get(inputs['sample_id'])
        elif name == 'get_dataset':
            result = crucible_client.datasets.get(inputs['dataset_id'], include_metadata=True)
        elif name == 'search_samples':
            q = inputs['query'].lower()
            result = [
                {'id': s['unique_id'], 'name': s['sample_name'], 'type': s.get('sample_type', '')}
                for s in pc.get('samples', [])
                if q in s['sample_name'].lower()
            ]
        elif name == 'search_datasets':
            q = inputs['query'].lower()
            result = [
                {'id': d['unique_id'], 'name': d['dataset_name'], 'measurement': d.get('measurement', '')}
                for d in pc.get('datasets', [])
                if q in d['dataset_name'].lower() or q in d.get('measurement', '').lower()
            ]
        elif name == 'list_samples_for_dataset':
            result = crucible_client.samples.list(dataset_id=inputs['dataset_id'])
        elif name == 'get_entity_graph':
            entity_type = inputs['entity_type']
            entity_id   = inputs['entity_id']
            G = get_entity_graph_nx(entity_id)

            nodes = []
            edges = [{'source': src, 'target': tgt} for src, tgt in G.edges()]
            for node_id, attrs in G.nodes(data=True):
                ntype = attrs.get('entity_type', entity_type)
                if ntype == 'sample':
                    s = pc['samples_by_id'].get(node_id, {})
                    datasets_for_sample = [
                        {'id': d['unique_id'], 'name': d.get('dataset_name', ''), 'measurement': d.get('measurement', '')}
                        for d in s.get('datasets', [])
                    ]
                    nodes.append({
                        'id': node_id,
                        'name': s.get('sample_name', attrs.get('name', node_id[:13])),
                        'type': 'sample',
                        'is_focal': node_id == entity_id,
                        'datasets': datasets_for_sample
                    })
                else:
                    ds = pc['datasets_by_id'].get(node_id, {})
                    nodes.append({
                        'id': node_id,
                        'name': ds.get('dataset_name', attrs.get('name', node_id[:13])),
                        'type': 'dataset',
                        'measurement': ds.get('measurement', ''),
                        'is_focal': node_id == entity_id
                    })
            result = {'nodes': nodes, 'edges': edges}
        else:
            result = {'error': f'Unknown tool: {name}'}
    except Exception as e:
        result = {'error': str(e)}

    text = json.dumps(result, default=str)
    return text[:3000] if len(text) > 3000 else text


def create_blueprint(auth, helpers):
    bp = Blueprint('chat', __name__)

    get_project        = helpers['get_project']
    is_user_in_project = helpers['is_user_in_project']
    get_entity_graph_nx = helpers['get_entity_graph_nx']

    _KEY_INFO_URL = 'https://api.cborg.lbl.gov/key/info'
    _AUTH_TOKEN   = os.getenv('ANTHROPIC_AUTH_TOKEN', '')

    @bp.route('/api/key-info')
    @auth.oidc_auth('orcid')
    def key_info():
        if not _AUTH_TOKEN:
            return {'error': 'ANTHROPIC_AUTH_TOKEN not set'}, 503
        resp = _requests.get(_KEY_INFO_URL,
                             headers={'Authorization': f'Bearer {_AUTH_TOKEN}'},
                             timeout=5)
        data = resp.json()
        info = data.get('info', {})
        return {
            'spend':            info.get('spend'),
            'max_budget':       info.get('max_budget'),
            'budget_reset_at':  info.get('budget_reset_at'),
            'key_alias':        info.get('key_alias'),
        }

    @bp.route('/<project_id>/chat')
    @auth.oidc_auth('orcid')
    def project_chat(project_id):
        if not is_user_in_project(project_id):
            abort(403)
        user_session = UserSession(session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        about = request.args.get('about')  # e.g. "sample:uuid" or "dataset:uuid"
        return render_template('chat.html', pc=pc, orcid=orcid, about=about)

    @bp.route('/<project_id>/api/chat', methods=['POST'])
    @auth.oidc_auth('orcid')
    def project_chat_api(project_id):
        if not is_user_in_project(project_id):
            abort(403)

        body = request.get_json(force=True)
        history = body.get('history', [])

        user_session = UserSession(session)
        orcid = user_session.userinfo['sub']
        pc = get_project(project_id, orcid)
        system_prompt = build_system_prompt(pc)

        def generate():
            messages = list(history)
            try:
                while True:
                    response = anthropic_client.messages.create(
                        model=CHAT_MODEL,
                        system=system_prompt,
                        messages=messages,
                        tools=CHAT_TOOL_DEFS,
                        max_tokens=4096
                    )

                    for block in response.content:
                        if block.type == 'text' and block.text:
                            yield f"data: {json.dumps({'type': 'text', 'delta': block.text})}\n\n"

                    if response.stop_reason == 'tool_use':
                        assistant_content = []
                        for b in response.content:
                            if b.type == 'text':
                                assistant_content.append({'type': 'text', 'text': b.text})
                            elif b.type == 'tool_use':
                                assistant_content.append({'type': 'tool_use', 'id': b.id, 'name': b.name, 'input': b.input})
                        messages.append({'role': 'assistant', 'content': assistant_content})

                        tool_results = []
                        for block in response.content:
                            if block.type == 'tool_use':
                                yield f"data: {json.dumps({'type': 'tool_call', 'name': block.name, 'input': block.input})}\n\n"

                                if block.name == 'get_thumbnail':
                                    dsid = block.input['dataset_id']
                                    try:
                                        thumbs = get_user_client().datasets.get_thumbnails(dsid)
                                        if thumbs:
                                            src = f"data:image/png;base64,{thumbs[0]['thumbnail_b64str']}"
                                            label = pc['datasets_by_id'].get(dsid, {}).get('dataset_name', dsid[:13])
                                            yield f"data: {json.dumps({'type': 'image', 'src': src, 'label': label, 'dataset_id': dsid})}\n\n"
                                            result_text = f"Thumbnail for '{label}' retrieved and displayed to the user."
                                        else:
                                            result_text = "No thumbnail available for this dataset."
                                    except Exception as e:
                                        result_text = f"Failed to retrieve thumbnail: {e}"
                                else:
                                    result_text = execute_chat_tool(
                                        block.name, block.input,
                                        get_user_client(), pc,
                                        get_entity_graph_nx,
                                    )

                                yield f"data: {json.dumps({'type': 'tool_result', 'name': block.name, 'result': result_text})}\n\n"
                                tool_results.append({
                                    'type': 'tool_result',
                                    'tool_use_id': block.id,
                                    'content': result_text
                                })

                        messages.append({'role': 'user', 'content': tool_results})
                    else:
                        break

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'},
        )

    return bp
