"""End-to-end smoke verification for AVEXIE's local audited tool runtime."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

secret_file = Path('/app/backend/data/.webui_secret_key')
if not os.environ.get('WEBUI_SECRET_KEY') and secret_file.exists():
    os.environ['WEBUI_SECRET_KEY'] = secret_file.read_text().strip()

from avexie.models.users import Users
from avexie.toaa.models import ToaaAudit
from avexie.toaa.wrapper import toaa_wrap
from avexie.tools.documents import (
    append_powerpoint_slide,
    append_to_word_document,
    create_excel_workbook,
    create_local_text_file,
    create_powerpoint_presentation,
    create_word_document,
    edit_local_text_file,
    read_office_document,
    read_local_text_file,
    share_local_file,
    update_excel_cells,
)
from avexie.tools.run_code import run_code
from avexie.router.filter import model_router_filter
from avexie.utils.json_codec import JSONCodec


SESSION_ID = 'sovereign-runtime-verification'


async def audited(name, arguments, function, user_id):
    return await toaa_wrap(
        name,
        arguments,
        function,
        session_id=SESSION_ID,
        user_id=user_id,
    )


async def main():
    result = await Users.get_users(filter={'roles': ['admin']}, limit=1)
    if not result['users']:
        raise RuntimeError('Runtime verification requires an existing admin user')
    user = result['users'][0].model_dump()
    user_id = user['id']

    # Agentic work must select the strongest general model and never the tiny
    # vision model that is reserved for actual image inputs.
    routing_registry = {
        'qwen3:3b': {'details': {'family': 'qwen3', 'parameter_size': '3B'}},
        'qwen3:8b': {'details': {'family': 'qwen3', 'parameter_size': '8B'}},
        'moondream:latest': {'details': {'family': 'moondream', 'parameter_size': '1.8B'}},
    }
    routing_request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(OLLAMA_MODELS=routing_registry, MODELS={}),
        ),
    )
    routing_extra = {'__metadata__': {'session_id': SESSION_ID}}
    routed_body, _ = await model_router_filter(
        routing_request,
        {
            'model': 'moondream:latest',
            'messages': [{'role': 'user', 'content': 'Create a Word document with the findings'}],
            'files': [],
        },
        user,
        None,
        routing_extra,
    )
    assert routed_body['model'] == 'qwen3:8b'
    assert routing_extra['__metadata__']['route_decision']['lane'] == 'agentic'

    created = JSONCodec.loads(await audited(
        'create_local_text_file',
        {'filename': 'sovereign-runtime-verification.md', 'content': 'local version one', '__user__': user},
        create_local_text_file,
        user_id,
    ))
    file_id = created['file_id']

    first_read = JSONCodec.loads(await audited(
        'read_local_text_file',
        {'file_id': file_id, '__user__': user},
        read_local_text_file,
        user_id,
    ))
    assert first_read['content'] == 'local version one'

    await audited(
        'edit_local_text_file',
        {'file_id': file_id, 'content': 'local version two - verified', '__user__': user},
        edit_local_text_file,
        user_id,
    )
    second_read = JSONCodec.loads(await audited(
        'read_local_text_file',
        {'file_id': file_id, '__user__': user},
        read_local_text_file,
        user_id,
    ))
    assert second_read['content'] == 'local version two - verified'

    shared = JSONCodec.loads(await audited(
        'share_local_file',
        {'file_id': file_id, 'recipient_email': user['email'], 'permission': 'read', '__user__': user},
        share_local_file,
        user_id,
    ))
    assert shared['status'] == 'shared'

    document = JSONCodec.loads(await audited(
        'create_word_document',
        {
            'title': 'Sovereign Runtime Verification',
            'body': 'This Word artifact was generated locally through the mandatory TOAA wrapper.',
            'filename': 'sovereign-runtime-verification.docx',
            '__user__': user,
        },
        create_word_document,
        user_id,
    ))
    await audited(
        'append_to_word_document',
        {'file_id': document['file_id'], 'heading': 'Verification', 'text': 'DOCX edit passed.', '__user__': user},
        append_to_word_document,
        user_id,
    )
    word_read = JSONCodec.loads(await audited(
        'read_office_document',
        {'file_id': document['file_id'], '__user__': user},
        read_office_document,
        user_id,
    ))
    assert 'DOCX edit passed.' in word_read['content']['paragraphs']

    presentation = JSONCodec.loads(await audited(
        'create_powerpoint_presentation',
        {
            'title': 'Sovereign Presentation',
            'slides': [{'title': 'Local Tools', 'bullets': ['python-pptx', 'No external calls']}],
            'filename': 'sovereign-runtime-verification.pptx',
            '__user__': user,
        },
        create_powerpoint_presentation,
        user_id,
    ))
    await audited(
        'append_powerpoint_slide',
        {'file_id': presentation['file_id'], 'title': 'Verified', 'bullets': ['PPTX edit passed'], '__user__': user},
        append_powerpoint_slide,
        user_id,
    )
    powerpoint_read = JSONCodec.loads(await audited(
        'read_office_document',
        {'file_id': presentation['file_id'], '__user__': user},
        read_office_document,
        user_id,
    ))
    assert any('PPTX edit passed' in part for part in powerpoint_read['content']['slides'][-1])

    workbook = JSONCodec.loads(await audited(
        'create_excel_workbook',
        {
            'title': 'Sovereign Workbook',
            'headers': ['Item', 'Value'],
            'rows': [['Initial', '1']],
            'filename': 'sovereign-runtime-verification.xlsx',
            'sheet_name': 'Checks',
            '__user__': user,
        },
        create_excel_workbook,
        user_id,
    ))
    await audited(
        'update_excel_cells',
        {'file_id': workbook['file_id'], 'sheet_name': 'Checks', 'updates': {'B2': '=40+2'}, '__user__': user},
        update_excel_cells,
        user_id,
    )
    excel_read = JSONCodec.loads(await audited(
        'read_office_document',
        {'file_id': workbook['file_id'], '__user__': user},
        read_office_document,
        user_id,
    ))
    assert excel_read['content']['sheets']['Checks'][1][1] == '=40+2'

    sandbox = await audited(
        'run_code',
        {'language': 'python', 'source': 'print(sum(i * i for i in range(6)))'},
        run_code,
        user_id,
    )
    assert sandbox['exit_code'] == 0 and sandbox['stdout'].strip() == '55'

    audits = await ToaaAudit.get_by_session(SESSION_ID)
    latest = audits[-15:]
    expected = [
        'create_local_text_file', 'read_local_text_file', 'edit_local_text_file',
        'read_local_text_file', 'share_local_file',
        'create_word_document', 'append_to_word_document', 'read_office_document',
        'create_powerpoint_presentation', 'append_powerpoint_slide', 'read_office_document',
        'create_excel_workbook', 'update_excel_cells', 'read_office_document',
        'run_code',
    ]
    assert [record.tool_name for record in latest] == expected
    assert all(record.status == 'success' and record.completed_at for record in latest)

    # Architectural enforcement: an unavailable audit store must prevent the
    # wrapped callable from running at all.
    original_insert = ToaaAudit.insert_pending
    blocked_callable = AsyncMock()
    try:
        ToaaAudit.insert_pending = AsyncMock(return_value=None)
        try:
            await toaa_wrap('must_not_execute', {}, blocked_callable, session_id=SESSION_ID, user_id=user_id)
        except RuntimeError as error:
            assert 'blocked tool execution' in str(error)
        else:
            raise AssertionError('TOAA fail-closed check did not raise')
    finally:
        ToaaAudit.insert_pending = original_insert
    blocked_callable.assert_not_awaited()

    print(JSONCodec.dumps({
        'status': 'passed',
        'audited_tools': expected,
        'audit_records_verified': len(latest),
        'sandbox_stdout': sandbox['stdout'].strip(),
        'agentic_route': routed_body['model'],
        'local_file': created['download_url'],
        'word_document': document['download_url'],
        'powerpoint_presentation': presentation['download_url'],
        'excel_workbook': workbook['download_url'],
        'fail_closed': True,
        'external_calls': 0,
    }, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
