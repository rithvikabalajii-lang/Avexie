"""Prove that local artifact and sandbox tools are injected into every native agent session."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace


secret_file = Path('/app/backend/data/.webui_secret_key')
if not os.environ.get('WEBUI_SECRET_KEY') and secret_file.exists():
    os.environ['WEBUI_SECRET_KEY'] = secret_file.read_text().strip()

from avexie.models.users import Users
from avexie.utils.json_codec import JSONCodec
from avexie.utils.tools import get_builtin_tools


REQUIRED_TOOLS = {
    'run_code',
    'create_word_document',
    'create_powerpoint_presentation',
    'create_excel_workbook',
    'read_office_document',
    'append_to_word_document',
    'append_powerpoint_slide',
    'update_excel_cells',
}


async def main() -> None:
    result = await Users.get_users(filter={'roles': ['admin']}, limit=1)
    if not result['users']:
        raise RuntimeError('Native tool verification requires an existing admin user')
    user = result['users'][0].model_dump()
    request = SimpleNamespace(state=SimpleNamespace(internal=False, direct=False))
    catalog = await get_builtin_tools(
        request,
        {
            '__user__': user,
            '__metadata__': {'session_id': 'native-tool-catalog-verification'},
        },
        features={},
        model={'info': {'meta': {'capabilities': {'builtin_tools': True}}}},
    )
    missing = REQUIRED_TOOLS - set(catalog)
    if missing:
        raise AssertionError(f'Missing native tools: {sorted(missing)}')
    invalid = {
        name for name in REQUIRED_TOOLS
        if catalog[name].get('type') != 'builtin'
        or catalog[name].get('tool_id') != f'builtin:{name}'
        or not catalog[name].get('spec', {}).get('parameters')
    }
    if invalid:
        raise AssertionError(f'Invalid native tool specifications: {sorted(invalid)}')

    import docx
    import openpyxl
    import pptx

    print(JSONCodec.dumps({
        'status': 'passed',
        'setup_required_by_user': False,
        'native_tools': sorted(REQUIRED_TOOLS),
        'libraries': {
            'python-docx': docx.__version__,
            'python-pptx': pptx.__version__,
            'openpyxl': openpyxl.__version__,
        },
    }, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
