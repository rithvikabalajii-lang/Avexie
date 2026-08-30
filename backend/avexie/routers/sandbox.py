"""Authenticated API surface for local IDE inference and sandbox execution."""

import json
import re
from typing import Any

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from avexie.models.config import Config
from avexie.router.filter import _capability, _parse_param_size
from avexie.tools.run_code import run_code
from avexie.utils.auth import get_verified_user


router = APIRouter()


@router.get('/sovereignty')
async def sovereignty_status(_user=Depends(get_verified_user)) -> dict[str, Any]:
    """Describe the runtime network policy used by the offline demo monitor."""
    return {
        'mode': 'enforced-offline',
        'external_calls': 0,
        'allowed_local_services': ['ollama:11434', 'judge0:2358', 'chroma:persistent'],
        'enforcement': [
            'Docker internal networks have no external gateway',
            'Judge0 submissions have network disabled',
            'OpenAI-compatible cloud connectors are disabled',
            'Chroma telemetry and update checks are disabled',
        ],
    }


class SandboxLimits(BaseModel):
    cpu_time: float | None = Field(default=None, gt=0)
    wall_time: float | None = Field(default=None, gt=0)
    memory_kb: int | None = Field(default=None, gt=0)
    max_processes: int | None = Field(default=None, gt=0)


class RunCodeForm(BaseModel):
    language: str = Field(min_length=1, max_length=32)
    source: str = Field(min_length=1)
    stdin: str = ''
    limits: SandboxLimits | None = None


class IdeFile(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=250_000)


class IdeAgentForm(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    files: list[IdeFile] = Field(min_length=1, max_length=200)
    active_path: str = Field(min_length=1, max_length=240)


def _pick_coding_model(models: dict[str, dict]) -> str:
    candidates = []
    for model_id, item in models.items():
        details = item.get('details') or {}
        candidates.append(
            (
                _capability(model_id, details.get('family', '')) == 'coding',
                _parse_param_size(details.get('parameter_size')),
                model_id,
            )
        )
    if not candidates:
        raise HTTPException(status_code=503, detail='No local Ollama models are available')
    # Prefer a coding specialist, then the largest locally available model.
    return max(candidates)[2]


def _parse_ide_response(content: str, known_paths: set[str]) -> list[dict[str, str]]:
    fenced = re.search(r'```(?:json)?\s*([\s\S]*?)```', content, re.IGNORECASE)
    candidate = fenced.group(1) if fenced else content
    try:
        payload = json.loads(candidate.strip())
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=502, detail='The local coding model returned invalid edit JSON') from error

    edits = payload.get('edits') if isinstance(payload, dict) else None
    if not isinstance(edits, list) or not edits:
        raise HTTPException(status_code=502, detail='The local coding model returned no file edits')

    normalized = []
    for edit in edits:
        path = str(edit.get('path', '')).replace('\\', '/').strip('/')
        new_content = edit.get('content')
        if not path or '..' in path.split('/') or not isinstance(new_content, str):
            raise HTTPException(status_code=502, detail='The local coding model returned an unsafe edit')
        normalized.append({'path': path, 'content': new_content})
    return normalized


@router.post('/run')
async def execute_code(
    form_data: RunCodeForm,
    _user=Depends(get_verified_user),
) -> dict[str, Any]:
    """Execute one source file with deployment-enforced, no-egress limits."""

    try:
        return await run_code(
            language=form_data.language,
            source=form_data.source,
            stdin=form_data.stdin,
            limits=form_data.limits.model_dump(exclude_none=True) if form_data.limits else None,
        )
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post('/ide-agent')
async def run_ide_agent(
    request: Request,
    form_data: IdeAgentForm,
    _user=Depends(get_verified_user),
) -> dict[str, Any]:
    """Ask a locally hosted Ollama coding model for whole-file edits.

    This endpoint deliberately bypasses the main chat pipeline. It accepts only
    the browser IDE workspace and talks only to the configured local Ollama node.
    """

    ollama_models = dict(getattr(request.app.state, 'OLLAMA_MODELS', {}) or {})
    model_id = _pick_coding_model(ollama_models)
    base_urls = await Config.get('ollama.base_urls') or ['http://ollama:11434']
    base_url = str(base_urls[0]).rstrip('/')
    if not base_url.startswith(('http://ollama:', 'http://localhost:', 'http://127.0.0.1:')):
        raise HTTPException(status_code=503, detail='IDE inference requires a local Ollama endpoint')

    manifest = '\n\n'.join(
        f'FILE: {item.path}\n```\n{item.content}\n```' for item in form_data.files
    )
    system = (
        'You are a local coding agent embedded in an IDE. Return JSON only with shape '
        '{"summary":"...","edits":[{"path":"relative/path","content":"complete new file content"}]}. '
        'Return only files that need changes. Preserve unrelated code. Never use markdown fences.'
    )
    payload = {
        'model': model_id,
        'stream': False,
        'format': 'json',
        'keep_alive': '5m',
        'messages': [
            {'role': 'system', 'content': system},
            {
                'role': 'user',
                'content': (
                    f'Request: {form_data.prompt}\nActive file: {form_data.active_path}\n\n'
                    f'Workspace:\n{manifest}'
                ),
            },
        ],
        'options': {'temperature': 0.1},
    }
    try:
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f'{base_url}/api/chat', json=payload) as response:
                body = await response.json()
                if response.status >= 400:
                    raise HTTPException(status_code=503, detail=body.get('error', 'Local Ollama request failed'))
    except HTTPException:
        raise
    except (aiohttp.ClientError, TimeoutError) as error:
        raise HTTPException(status_code=503, detail=f'Local Ollama is unavailable: {error}') from error

    content = ((body.get('message') or {}).get('content') or '').strip()
    edits = _parse_ide_response(content, {item.path for item in form_data.files})
    return {
        'model': model_id,
        'summary': 'Local coding model proposed workspace changes',
        'edits': edits,
        'network': {'endpoint': base_url, 'external_calls': 0},
    }
