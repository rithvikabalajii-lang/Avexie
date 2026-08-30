"""Local document artifact tools."""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from uuid import uuid4

from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from pptx import Presentation

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


async def _store_artifact(
    contents: bytes,
    filename: str,
    content_type: str,
    generated_by: str,
    user: dict,
) -> str:
    file_id = str(uuid4())
    _, path = Storage.upload_file(
        io.BytesIO(contents),
        f'{file_id}_{filename}',
        {'Avexie-File-Id': file_id},
    )
    record = await Files.insert_new_file(
        user['id'],
        FileForm(
            id=file_id,
            hash=hashlib.sha256(contents).hexdigest(),
            filename=filename,
            path=path,
            data={'generated_by': generated_by},
            meta={
                'name': filename,
                'content_type': content_type,
                'size': len(contents),
                'local_only': True,
            },
        ),
    )
    if record is None:
        Storage.delete_file(path)
        return JSONCodec.dumps({'error': 'Could not register the generated local file'})
    return _download_result(file_id, filename, 'created')


async def _replace_artifact(record, contents: bytes, generated_by: str) -> str:
    path = Storage.get_file(record.path)
    directory = os.path.dirname(path)
    with tempfile.NamedTemporaryFile('wb', dir=directory, delete=False) as handle:
        handle.write(contents)
        temporary_path = handle.name
    os.replace(temporary_path, path)
    updated = await Files.update_file_by_id(
        record.id,
        FileUpdateForm(
            hash=hashlib.sha256(contents).hexdigest(),
            data={'generated_by': generated_by},
            meta={'size': len(contents), 'local_only': True},
        ),
    )
    if updated is None:
        return JSONCodec.dumps({'error': 'File changed but metadata update failed'})
    return _download_result(record.id, record.filename, 'updated')


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


async def create_word_document(
    title: str,
    body: str,
    filename: str = 'approval-note.docx',
    __user__: dict | None = None,
) -> str:
    """Create a real .docx Word file locally with python-docx.

    MUST be used whenever the user asks to create, save, export, or deliver a
    Word document, DOCX, report, memo, letter, or approval note. Do not merely
    print document text in chat when the user requested a file.

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
    return await _store_artifact(
        buffer.getvalue(),
        safe_name,
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'python-docx',
        __user__,
    )


async def create_powerpoint_presentation(
    title: str,
    slides: list[dict],
    filename: str = 'presentation.pptx',
    __user__: dict | None = None,
) -> str:
    """Create a real .pptx presentation locally with python-pptx.

    MUST be used when the user asks for a PowerPoint, PPTX, slide deck, or
    presentation file. Each slides item must contain a title and a bullets list.

    :param title: Presentation title used on the opening slide
    :param slides: Slide objects such as [{"title": "Findings", "bullets": ["Item one"]}]
    :param filename: Output filename ending in .pptx
    """
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    if not slides:
        return JSONCodec.dumps({'error': 'At least one content slide is required'})
    safe_name = _safe_filename(filename, 'presentation.pptx')
    if not safe_name.lower().endswith('.pptx'):
        safe_name += '.pptx'

    presentation = Presentation()
    title_slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    title_slide.shapes.title.text = title.strip() or 'Presentation'
    if len(title_slide.placeholders) > 1:
        title_slide.placeholders[1].text = 'Created locally by AVEXIE'

    for slide_data in slides[:50]:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = str(slide_data.get('title') or 'Slide')
        body_shape = slide.placeholders[1]
        body_shape.text = ''
        bullets = slide_data.get('bullets') or []
        for index, bullet in enumerate(bullets[:20]):
            paragraph = body_shape.text_frame.paragraphs[0] if index == 0 else body_shape.text_frame.add_paragraph()
            paragraph.text = str(bullet)
            paragraph.level = 0

    buffer = io.BytesIO()
    presentation.save(buffer)
    return await _store_artifact(
        buffer.getvalue(),
        safe_name,
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'python-pptx',
        __user__,
    )


async def create_excel_workbook(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    filename: str = 'workbook.xlsx',
    sheet_name: str = 'Sheet1',
    __user__: dict | None = None,
) -> str:
    """Create a real .xlsx spreadsheet locally with openpyxl.

    MUST be used when the user asks to create, save, export, or deliver an Excel
    workbook, XLSX file, or spreadsheet. Values beginning with '=' are formulas.

    :param title: Workbook title stored in document properties
    :param headers: Column header labels
    :param rows: Table rows in the same column order as headers
    :param filename: Output filename ending in .xlsx
    :param sheet_name: Worksheet name
    """
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    if not headers and not rows:
        return JSONCodec.dumps({'error': 'Headers or rows are required'})
    safe_name = _safe_filename(filename, 'workbook.xlsx')
    if not safe_name.lower().endswith('.xlsx'):
        safe_name += '.xlsx'

    workbook = Workbook()
    workbook.properties.title = title.strip() or 'Workbook'
    worksheet = workbook.active
    worksheet.title = (sheet_name.strip() or 'Sheet1')[:31]
    if headers:
        worksheet.append([str(value) for value in headers])
    for row in rows[:10_000]:
        worksheet.append(list(row))
    if headers:
        worksheet.freeze_panes = 'A2'
        worksheet.auto_filter.ref = worksheet.dimensions
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
    for column_cells in worksheet.columns:
        width = min(max(len(str(cell.value or '')) for cell in column_cells) + 2, 50)
        worksheet.column_dimensions[column_cells[0].column_letter].width = width

    buffer = io.BytesIO()
    workbook.save(buffer)
    return await _store_artifact(
        buffer.getvalue(),
        safe_name,
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'openpyxl',
        __user__,
    )


async def read_office_document(
    file_id: str,
    __user__: dict | None = None,
) -> str:
    """Read text and cell content from a local DOCX, PPTX, or XLSX file."""
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    record = await _accessible_file(file_id, __user__, 'read')
    if record is None or not record.path:
        return JSONCodec.dumps({'error': 'File not found or access denied'})
    extension = os.path.splitext(record.filename)[1].lower()
    path = Storage.get_file(record.path)
    content = None
    if extension == '.docx':
        document = Document(path)
        content = {
            'paragraphs': [paragraph.text for paragraph in document.paragraphs if paragraph.text],
            'tables': [
                [[cell.text for cell in row.cells] for row in table.rows]
                for table in document.tables
            ],
        }
    elif extension == '.pptx':
        presentation = Presentation(path)
        content = {
            'slides': [
                [shape.text for shape in slide.shapes if hasattr(shape, 'text_frame') and shape.text]
                for slide in presentation.slides
            ]
        }
    elif extension == '.xlsx':
        workbook = load_workbook(path, data_only=False, read_only=True)
        content = {
            'sheets': {
                worksheet.title: [list(row) for row in worksheet.iter_rows(values_only=True)]
                for worksheet in workbook.worksheets
            }
        }
    else:
        return JSONCodec.dumps({'error': 'Supported office formats are DOCX, PPTX, and XLSX'})
    return JSONCodec.dumps({
        'file_id': file_id,
        'filename': record.filename,
        'content': content,
        'external_calls': 0,
    }, ensure_ascii=False)


async def append_to_word_document(
    file_id: str,
    text: str,
    heading: str = '',
    __user__: dict | None = None,
) -> str:
    """Append a heading and text to an existing local DOCX with python-docx."""
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    record = await _accessible_file(file_id, __user__, 'write')
    if record is None or not record.path or not record.filename.lower().endswith('.docx'):
        return JSONCodec.dumps({'error': 'DOCX file not found or access denied'})
    document = Document(Storage.get_file(record.path))
    if heading.strip():
        document.add_heading(heading.strip(), level=1)
    for paragraph in re.split(r'\n\s*\n', text.strip()):
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return await _replace_artifact(record, buffer.getvalue(), 'python-docx')


async def append_powerpoint_slide(
    file_id: str,
    title: str,
    bullets: list[str],
    __user__: dict | None = None,
) -> str:
    """Append one slide to an existing local PPTX with python-pptx."""
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    record = await _accessible_file(file_id, __user__, 'write')
    if record is None or not record.path or not record.filename.lower().endswith('.pptx'):
        return JSONCodec.dumps({'error': 'PPTX file not found or access denied'})
    presentation = Presentation(Storage.get_file(record.path))
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title.strip() or 'Slide'
    body_shape = slide.placeholders[1]
    body_shape.text = ''
    for index, bullet in enumerate(bullets[:20]):
        paragraph = body_shape.text_frame.paragraphs[0] if index == 0 else body_shape.text_frame.add_paragraph()
        paragraph.text = str(bullet)
    buffer = io.BytesIO()
    presentation.save(buffer)
    return await _replace_artifact(record, buffer.getvalue(), 'python-pptx')


async def update_excel_cells(
    file_id: str,
    updates: dict[str, str],
    sheet_name: str = 'Sheet1',
    __user__: dict | None = None,
) -> str:
    """Update cell values or formulas in an existing local XLSX with openpyxl.

    :param updates: Mapping of cell references to values, for example {"B2": "42", "C2": "=B2*2"}
    """
    if not __user__ or not __user__.get('id'):
        return JSONCodec.dumps({'error': 'User context not available'})
    record = await _accessible_file(file_id, __user__, 'write')
    if record is None or not record.path or not record.filename.lower().endswith('.xlsx'):
        return JSONCodec.dumps({'error': 'XLSX file not found or access denied'})
    workbook = load_workbook(Storage.get_file(record.path))
    if sheet_name not in workbook.sheetnames:
        return JSONCodec.dumps({'error': f'Worksheet not found: {sheet_name}'})
    worksheet = workbook[sheet_name]
    for cell_reference, value in list(updates.items())[:1_000]:
        worksheet[cell_reference] = value
    buffer = io.BytesIO()
    workbook.save(buffer)
    return await _replace_artifact(record, buffer.getvalue(), 'openpyxl')


# Backward-compatible name retained for existing saved tool-call history.
generate_word_document = create_word_document
