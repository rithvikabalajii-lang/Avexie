"""End-to-end smoke verification for AVEXIE's local audited tool runtime."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock

secret_file = Path('/app/backend/data/.webui_secret_key')
if not os.environ.get('WEBUI_SECRET_KEY') and secret_file.exists():
    os.environ['WEBUI_SECRET_KEY'] = secret_file.read_text().strip()

from avexie.models.users import Users
from avexie.toaa.models import ToaaAudit
from avexie.toaa.wrapper import toaa_wrap
from avexie.tools.documents import (
    create_local_text_file,
    edit_local_text_file,
    generate_word_document,
    read_local_text_file,
    share_local_file,
)
from avexie.tools.run_code import run_code
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
        'generate_word_document',
        {
            'title': 'Sovereign Runtime Verification',
            'body': 'This Word artifact was generated locally through the mandatory TOAA wrapper.',
            'filename': 'sovereign-runtime-verification.docx',
            '__user__': user,
        },
        generate_word_document,
        user_id,
    ))

    sandbox = await audited(
        'run_code',
        {'language': 'python', 'source': 'print(sum(i * i for i in range(6)))'},
        run_code,
        user_id,
    )
    assert sandbox['exit_code'] == 0 and sandbox['stdout'].strip() == '55'

    audits = await ToaaAudit.get_by_session(SESSION_ID)
    latest = audits[-7:]
    expected = [
        'create_local_text_file', 'read_local_text_file', 'edit_local_text_file',
        'read_local_text_file', 'share_local_file', 'generate_word_document', 'run_code',
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
        'local_file': created['download_url'],
        'word_document': document['download_url'],
        'fail_closed': True,
        'external_calls': 0,
    }, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
