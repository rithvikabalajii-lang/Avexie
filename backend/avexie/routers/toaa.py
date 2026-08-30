"""Admin-only API for inspecting immutable TOAA agent-action records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from avexie.models.users import Users
from avexie.toaa.models import ToaaAudit, ToaaAuditRecordModel
from avexie.utils.auth import get_admin_user


router = APIRouter()


class AuditUser(BaseModel):
    id: str
    name: str
    email: str


class AdminAuditRecord(ToaaAuditRecordModel):
    user: AuditUser | None = None


class AdminAuditResponse(BaseModel):
    items: list[AdminAuditRecord]
    total: int
    page: int
    limit: int
    summary: dict[str, int]


@router.get('/', response_model=AdminAuditResponse)
async def list_agent_action_audits(
    user_id: str | None = None,
    status: str | None = Query(default=None, pattern='^(pending|success|error|blocked)$'),
    query: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    _admin=Depends(get_admin_user),
) -> AdminAuditResponse:
    """List all users' agent tool executions; inaccessible to non-admins."""
    result = await ToaaAudit.get_admin_page(
        user_id=user_id,
        status=status,
        query=query,
        offset=(page - 1) * limit,
        limit=limit,
    )
    user_ids = list({item.user_id for item in result['items']})
    users = await Users.get_users_by_user_ids(user_ids) if user_ids else []
    user_map = {
        item.id: AuditUser(id=item.id, name=item.name, email=item.email)
        for item in users
    }
    return AdminAuditResponse(
        items=[
            AdminAuditRecord(**item.model_dump(), user=user_map.get(item.user_id))
            for item in result['items']
        ],
        total=result['total'],
        page=page,
        limit=limit,
        summary=result['summary'],
    )
