"""Local document artifact tools."""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from uuid import uuid4

from docx import Document

from avexie.models.access_grants import AccessGrants
from avexie.models.files import FileForm, FileUpdateForm, Files
from avexie.models.users import Users
from avexie.storage.provider import Storage
from avexie.utils.json_codec import JSONCodec


MAX_LOCAL_TEXT_BYTES = 2 * 1024 * 1024
SAFE_TEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.json', '.yaml', '.yml', '.xml', '.html', '.css',
    '.js', '.ts', '.tsx', '.jsx', '.py', '.java', '.c', '.cpp', '.h', '.hpp',
    '.rs', '.go', '.sh', '.sql', '.toml', '.ini', '.env', '.log',
}


def _safe_filename(filename: str, fallback: str = 'document.txt') -> str:
    name = re.sub(r'[^A-Za-z0-9._ -]+', '-', os.path.basename(filename or '')).strip(' .-')
    return name or fallback


def _download_result(file_id: str, filename: str, status: str) -> str:
    return JSONCodec.dumps({
        'status': status,
        'file_id': file_id,
        'filename': filename,
        'download_url': f'/api/v1/files/{file_id}/content?attachment=true',
        'external_calls': 0,
    })


async def _accessible_file(file_id: str, user: dict, permission: str):
    record = await Files.get_file_by_id(file_id)
    if record is None:
        return None
    if record.user_id == user['id'] or user.get('role') == 'admin':
        return record
    if await AccessGrants.has_access(
        user_id=user['id'],
        resource_type='file',
        resource_id=file_id,
        permission=permission,
    ):
        return record
    return None


async def create_local_text_file(
    filename: str,
    content: str,
    __user__: dict | None = None,
) -> str:
    """Create a text or source-code file in the user's local AVEXIE storage.

    The filename is sanitized and only safe text/source extensions are accepted.
    Returns a local authenticated download link; no external service is used.
    """
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    safe_name = _safe_filename(filename)
    extension = os.path.splitext(safe_name)[1].lower()
    if extension not in SAFE_TEXT_EXTENSIONS:
        return JSONCodec.dumps({'error': f'Unsupported text file extension: {extension or "none"}'})
    contents = content.encode('utf-8')
    if not contents:
        return JSONCodec.dumps({'error': 'File content cannot be empty'})
    if len(contents) > MAX_LOCAL_TEXT_BYTES:
        return JSONCodec.dumps({'error': 'File exceeds the 2 MiB local text limit'})

    file_id = str(uuid4())
    _, path = Storage.upload_file(io.BytesIO(contents), f'{file_id}_{safe_name}', {'Avexie-File-Id': file_id})
    record = await Files.insert_new_file(
        __user__['id'],
        FileForm(
            id=file_id,
            hash=hashlib.sha256(contents).hexdigest(),
            filename=safe_name,
            path=path,
            data={'generated_by': 'create_local_text_file'},
            meta={'name': safe_name, 'content_type': 'text/plain; charset=utf-8', 'size': len(contents), 'local_only': True},
        ),
    )
    if record is None:
        return JSONCodec.dumps({'error': 'Could not register the local file'})
    return _download_result(file_id, safe_name, 'created')


async def read_local_text_file(
    file_id: str,
    max_chars: int = 100_000,
    __user__: dict | None = None,
) -> str:
    """Read a locally stored text/source file owned by the current user."""
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    record = await _accessible_file(file_id, __user__, 'read')
    if record is None or not record.path:
        return JSONCodec.dumps({'error': 'File not found or access denied'})
    if os.path.splitext(record.filename)[1].lower() not in SAFE_TEXT_EXTENSIONS:
        return JSONCodec.dumps({'error': 'This tool only reads text/source files'})
    limit = max(1, min(int(max_chars), 500_000))
    with open(Storage.get_file(record.path), 'r', encoding='utf-8', errors='replace') as handle:
        content = handle.read(limit + 1)
    truncated = len(content) > limit
    return JSONCodec.dumps({
        'file_id': record.id,
        'filename': record.filename,
        'content': content[:limit],
        'truncated': truncated,
        'external_calls': 0,
    }, ensure_ascii=False)


async def edit_local_text_file(
    file_id: str,
    content: str,
    __user__: dict | None = None,
) -> str:
    """Replace the contents of a local text/source file owned by the user."""
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    record = await _accessible_file(file_id, __user__, 'write')
    if record is None or not record.path:
        return JSONCodec.dumps({'error': 'File not found or access denied'})
    if os.path.splitext(record.filename)[1].lower() not in SAFE_TEXT_EXTENSIONS:
        return JSONCodec.dumps({'error': 'This tool only edits text/source files'})
    contents = content.encode('utf-8')
    if not contents:
        return JSONCodec.dumps({'error': 'File content cannot be empty'})
    if len(contents) > MAX_LOCAL_TEXT_BYTES:
        return JSONCodec.dumps({'error': 'File exceeds the 2 MiB local text limit'})

    path = Storage.get_file(record.path)
    directory = os.path.dirname(path)
    with tempfile.NamedTemporaryFile('wb', dir=directory, delete=False) as handle:
        handle.write(contents)
        temporary_path = handle.name
    os.replace(temporary_path, path)
    updated = await Files.update_file_by_id(
        file_id,
        FileUpdateForm(
            hash=hashlib.sha256(contents).hexdigest(),
            data={'generated_by': 'edit_local_text_file'},
            meta={'size': len(contents), 'local_only': True},
        ),
    )
    if updated is None:
        return JSONCodec.dumps({'error': 'File changed but metadata update failed'})
    return _download_result(file_id, record.filename, 'updated')


async def list_local_files(limit: int = 50, __user__: dict | None = None) -> str:
    """List the current user's locally stored files and authenticated download links."""
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    records = await Files.get_file_list(user_id=__user__['id'], limit=max(1, min(int(limit), 100)))
    return JSONCodec.dumps([
        {
            'file_id': item.id,
            'filename': item.filename,
            'size': (item.meta.size if item.meta else None),
            'download_url': f'/api/v1/files/{item.id}/content?attachment=true',
            'local_only': True,
        }
        for item in records.items
    ], ensure_ascii=False)


async def share_local_file(
    file_id: str,
    recipient_email: str,
    permission: str = 'read',
    __user__: dict | None = None,
) -> str:
    """Share an owned local file with another AVEXIE user.

    Creates an application access grant; the bytes remain on local storage and
    the recipient uses the same authenticated local download URL.
    """
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    record = await Files.get_file_by_id_and_user_id(file_id, __user__['id'])
    if record is None:
        return JSONCodec.dumps({'error': 'File not found or only its owner can share it'})
    if permission not in ('read', 'write'):
        return JSONCodec.dumps({'error': 'Permission must be read or write'})
    recipient = await Users.get_user_by_email(recipient_email.strip())
    if recipient is None:
        return JSONCodec.dumps({'error': 'Recipient is not an AVEXIE user'})
    grant = await AccessGrants.grant_access(
        resource_type='file',
        resource_id=file_id,
        principal_type='user',
        principal_id=recipient.id,
        permission=permission,
    )
    if grant is None:
        return JSONCodec.dumps({'error': 'Could not create the local file access grant'})
    return JSONCodec.dumps({
        'status': 'shared',
        'file_id': file_id,
        'filename': record.filename,
        'recipient': recipient.email,
        'permission': permission,
        'download_url': f'/api/v1/files/{file_id}/content?attachment=true',
        'external_calls': 0,
    })


async def generate_word_document(
    title: str,
    body: str,
    filename: str = 'approval-note.docx',
    __user__: dict | None = None,
) -> str:
    """Create a downloadable Word document entirely on the local AVEXIE host.

    Use this after extracting or analysing a report when the user requests an
    approval note, report, memo, or other Word artifact.

    :param title: Document title
    :param body: Complete document text; blank lines create paragraphs
    :param filename: Output filename ending in .docx
    :return: JSON containing the local file id and authenticated download URL
    """
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})

    safe_name = _safe_filename(filename, 'approval-note.docx')
    if not safe_name.lower().endswith('.docx'):
        safe_name += '.docx'

    document = Document()
    document.add_heading(title.strip() or 'Document', level=0)
    for paragraph in re.split(r'\n\s*\n', body.strip()):
        document.add_paragraph(paragraph.strip())

    buffer = io.BytesIO()
    document.save(buffer)
    contents = buffer.getvalue()
    file_id = str(uuid4())
    storage_name = f'{file_id}_{safe_name}'
    _, path = Storage.upload_file(io.BytesIO(contents), storage_name, {'Avexie-File-Id': file_id})
    await Files.insert_new_file(
        __user__['id'],
        FileForm(
            id=file_id,
            hash=hashlib.sha256(contents).hexdigest(),
            filename=safe_name,
            path=path,
            data={'generated_by': 'generate_word_document'},
            meta={
                'name': safe_name,
                'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'size': len(contents),
                'local_only': True,
            },
        ),
    )
    return _download_result(file_id, safe_name, 'created')
