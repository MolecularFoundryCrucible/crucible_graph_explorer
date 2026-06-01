import asyncio
import json
import os
import queue as _queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from flask import Blueprint, render_template, request, Response, session, stream_with_context
from flask_pyoidc.user_session import UserSession

from utils.auth import get_user_client

_vertex_project = os.getenv("VERTEX_PROJECT_ID", "mf-crucible")
_vertex_region  = os.getenv("VERTEX_REGION", "us-central1")
_model_name     = os.getenv("CHAT_MODEL", "gemini-2.5-pro")

_model = GoogleModel(
    _model_name,
    provider=GoogleProvider(vertexai=True, project=_vertex_project, location=_vertex_region),
)

# Single persistent event loop in a background thread so the GoogleProvider's
# httpx.AsyncClient is never tied to a loop that gets closed between requests.
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()


@dataclass
class _ChatDeps:
    pc: dict
    crucible_client: Any
    get_entity_graph_nx: Any
    sse_events: deque = field(default_factory=deque)


agent: Agent[_ChatDeps, str] = Agent(_model)


# ── System prompt ─────────────────────────────────────────────────────────────

_FULL_LIST_THRESHOLD = 150


def _grouped_summary(items, name_key, type_key, examples=3):
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
    samples    = pc.get('samples', [])
    datasets   = pc.get('datasets', [])

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


@agent.system_prompt
def _system_prompt(ctx: RunContext[_ChatDeps]) -> str:
    return build_system_prompt(ctx.deps.pc)


# ── Tools ─────────────────────────────────────────────────────────────────────

def _truncate(obj) -> str:
    text = json.dumps(obj, default=str)
    return text[:3000] if len(text) > 3000 else text


def _emit(ctx: RunContext[_ChatDeps], name: str, inputs: dict, result: str) -> str:
    ctx.deps.sse_events.append(('tool_call', name, inputs))
    ctx.deps.sse_events.append(('tool_result', name, result))
    return result


@agent.tool
def get_sample(ctx: RunContext[_ChatDeps], sample_id: str) -> str:
    """Retrieve full details for a single sample by its unique ID."""
    try:
        result = ctx.deps.crucible_client.samples.get(sample_id)
    except Exception as e:
        result = {'error': str(e)}
    return _emit(ctx, 'get_sample', {'sample_id': sample_id}, _truncate(result))


@agent.tool
def get_dataset(ctx: RunContext[_ChatDeps], dataset_id: str) -> str:
    """Retrieve full details (including scientific metadata) for a dataset by its unique ID."""
    try:
        result = ctx.deps.crucible_client.datasets.get(dataset_id, include_metadata=True)
    except Exception as e:
        result = {'error': str(e)}
    return _emit(ctx, 'get_dataset', {'dataset_id': dataset_id}, _truncate(result))


@agent.tool
def search_samples(ctx: RunContext[_ChatDeps], query: str) -> str:
    """Search samples in the project by name substring."""
    q = query.lower()
    result = [
        {'id': s['unique_id'], 'name': s['sample_name'], 'type': s.get('sample_type', '')}
        for s in ctx.deps.pc.get('samples', [])
        if q in s['sample_name'].lower()
    ]
    return _emit(ctx, 'search_samples', {'query': query}, _truncate(result))


@agent.tool
def search_datasets(ctx: RunContext[_ChatDeps], query: str) -> str:
    """Search datasets in the project by name or measurement type substring."""
    q = query.lower()
    result = [
        {'id': d['unique_id'], 'name': d['dataset_name'], 'measurement': d.get('measurement', '')}
        for d in ctx.deps.pc.get('datasets', [])
        if q in d['dataset_name'].lower() or q in d.get('measurement', '').lower()
    ]
    return _emit(ctx, 'search_datasets', {'query': query}, _truncate(result))


@agent.tool
def list_samples_for_dataset(ctx: RunContext[_ChatDeps], dataset_id: str) -> str:
    """List all samples associated with a given dataset."""
    try:
        result = ctx.deps.crucible_client.samples.list(dataset_id=dataset_id, limit=1000)
    except Exception as e:
        result = {'error': str(e)}
    return _emit(ctx, 'list_samples_for_dataset', {'dataset_id': dataset_id}, _truncate(result))


@agent.tool
def get_entity_graph(ctx: RunContext[_ChatDeps], entity_type: str, entity_id: str) -> str:
    """Return the lineage graph for a sample or dataset: ancestors, descendants, relationships,
    and associated datasets. Use to understand provenance, processing history, or measurements.
    entity_type must be 'sample' or 'dataset'."""
    try:
        G = ctx.deps.get_entity_graph_nx(entity_id)
        pc = ctx.deps.pc
        nodes, edges = [], [{'source': src, 'target': tgt} for src, tgt in G.edges()]
        for node_id, attrs in G.nodes(data=True):
            ntype = attrs.get('entity_type', entity_type)
            if ntype == 'sample':
                s = pc['samples_by_id'].get(node_id, {})
                nodes.append({
                    'id': node_id,
                    'name': s.get('sample_name', attrs.get('name', node_id[:13])),
                    'type': 'sample',
                    'is_focal': node_id == entity_id,
                    'datasets': [
                        {'id': d['unique_id'], 'name': d.get('dataset_name', ''), 'measurement': d.get('measurement', '')}
                        for d in s.get('datasets', [])
                    ],
                })
            else:
                ds = pc['datasets_by_id'].get(node_id, {})
                nodes.append({
                    'id': node_id,
                    'name': ds.get('dataset_name', attrs.get('name', node_id[:13])),
                    'type': 'dataset',
                    'measurement': ds.get('measurement', ''),
                    'is_focal': node_id == entity_id,
                })
        result = {'nodes': nodes, 'edges': edges}
    except Exception as e:
        result = {'error': str(e)}
    return _emit(ctx, 'get_entity_graph', {'entity_type': entity_type, 'entity_id': entity_id}, _truncate(result))


@agent.tool
def get_thumbnail(ctx: RunContext[_ChatDeps], dataset_id: str) -> str:
    """Retrieve and display a thumbnail image for a dataset.
    Use when the user asks to see an image, photo, or thumbnail."""
    deps = ctx.deps
    deps.sse_events.append(('tool_call', 'get_thumbnail', {'dataset_id': dataset_id}))
    try:
        thumbs = deps.crucible_client.datasets.get_thumbnails(dataset_id)
        if thumbs:
            src   = f"data:image/png;base64,{thumbs[0]['thumbnail_b64str']}"
            label = deps.pc['datasets_by_id'].get(dataset_id, {}).get('dataset_name', dataset_id[:13])
            deps.sse_events.append(('image', src, label, dataset_id))
            result = f"Thumbnail for '{label}' retrieved and displayed to the user."
        else:
            result = "No thumbnail available for this dataset."
    except Exception as e:
        result = f"Failed to retrieve thumbnail: {e}"
    deps.sse_events.append(('tool_result', 'get_thumbnail', result))
    return result


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _drain(events: deque) -> list[str]:
    out = []
    while events:
        ev = events.popleft()
        kind = ev[0]
        if kind == 'tool_call':
            out.append(_sse({'type': 'tool_call', 'name': ev[1], 'input': ev[2]}))
        elif kind == 'tool_result':
            out.append(_sse({'type': 'tool_result', 'name': ev[1], 'result': ev[2]}))
        elif kind == 'image':
            out.append(_sse({'type': 'image', 'src': ev[1], 'label': ev[2], 'dataset_id': ev[3]}))
    return out


def _history_to_messages(history: list[dict]):
    msgs = []
    for msg in history:
        if msg['role'] == 'user':
            msgs.append(ModelRequest(parts=[UserPromptPart(content=msg['content'])]))
        elif msg['role'] == 'assistant':
            msgs.append(ModelResponse(parts=[TextPart(content=msg['content'])]))
    return msgs


# ── Blueprint ─────────────────────────────────────────────────────────────────

def create_blueprint(auth, helpers):
    bp = Blueprint('chat', __name__)

    get_project         = helpers['get_project']
    get_entity_graph_nx = helpers['get_entity_graph_nx']

    @bp.route('/<project_id>/chat')
    @auth.oidc_auth('orcid')
    def project_chat(project_id):
        user_session = UserSession(session)
        orcid = user_session.userinfo['sub']
        pc    = get_project(project_id, orcid)
        about = request.args.get('about')
        return render_template('chat.html', pc=pc, orcid=orcid, about=about)

    @bp.route('/<project_id>/api/chat', methods=['POST'])
    @auth.oidc_auth('orcid')
    def project_chat_api(project_id):
        body    = request.get_json(force=True)
        history = body.get('history', [])

        user_session = UserSession(session)
        orcid        = user_session.userinfo['sub']
        pc           = get_project(project_id, orcid)

        # Capture request-scoped resources before spawning thread
        crucible_client = get_user_client()
        deps = _ChatDeps(
            pc=pc,
            crucible_client=crucible_client,
            get_entity_graph_nx=get_entity_graph_nx,
        )

        user_prompt  = history[-1]['content'] if history else ''
        past_history = _history_to_messages(history[:-1])

        def generate():
            q = _queue.Queue()

            async def run():
                try:
                    async with agent.run_stream(
                        user_prompt,
                        message_history=past_history,
                        deps=deps,
                    ) as result:
                        async for text in result.stream_text(delta=True, debounce_by=None):
                            for ev in _drain(deps.sse_events):
                                q.put(ev)
                            q.put(_sse({'type': 'text', 'delta': text}))
                        for ev in _drain(deps.sse_events):
                            q.put(ev)
                        u = result.usage()
                        q.put(_sse({
                            'type': 'usage',
                            'input_tokens':  u.input_tokens,
                            'output_tokens': u.output_tokens,
                            'requests':      u.requests,
                            'tool_calls':    u.tool_calls,
                        }))
                except Exception as e:
                    q.put(_sse({'type': 'error', 'message': str(e)}))
                finally:
                    q.put(_sse({'type': 'done'}))
                    q.put(None)

            asyncio.run_coroutine_threadsafe(run(), _loop)

            while True:
                item = q.get()
                if item is None:
                    break
                yield item

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'},
        )

    return bp
