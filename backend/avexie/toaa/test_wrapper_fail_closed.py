"""Fail-closed guarantees for the mandatory TOAA execution wrapper."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from avexie.toaa.wrapper import toaa_wrap


@pytest.mark.asyncio
async def test_tool_does_not_run_when_pending_insert_fails(monkeypatch):
    tool = AsyncMock()
    monkeypatch.setattr(
        'avexie.toaa.wrapper.ToaaAudit.insert_pending',
        AsyncMock(side_effect=RuntimeError('database unavailable')),
    )

    with pytest.raises(RuntimeError, match='blocked tool execution'):
        await toaa_wrap('local_tool', {}, tool, session_id='session', user_id='user')

    tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_does_not_run_without_durable_pending_record(monkeypatch):
    tool = AsyncMock()
    monkeypatch.setattr('avexie.toaa.wrapper.ToaaAudit.insert_pending', AsyncMock(return_value=None))

    with pytest.raises(RuntimeError, match='blocked tool execution'):
        await toaa_wrap('local_tool', {}, tool, session_id='session', user_id='user')

    tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_requires_audit_finalization(monkeypatch):
    tool = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(
        'avexie.toaa.wrapper.ToaaAudit.insert_pending',
        AsyncMock(return_value=SimpleNamespace(id='audit-id')),
    )
    monkeypatch.setattr('avexie.toaa.wrapper.ToaaAudit.complete', AsyncMock(return_value=None))

    with pytest.raises(RuntimeError, match='audit finalization failed'):
        await toaa_wrap('local_tool', {}, tool, session_id='session', user_id='user')

    tool.assert_awaited_once()
