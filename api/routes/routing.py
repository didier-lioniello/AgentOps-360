"""Routing policy CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import authenticate
from api.deps import get_db
from core.router import Router, RouterError
from models.routing import RoutingPolicy

router = APIRouter()


@router.put("/{agent_name}")
async def upsert(
    agent_name: str,
    policy: RoutingPolicy,
    _claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if policy.agent != agent_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "policy.agent must match path")
    try:
        await Router(db).upsert_policy(policy)
    except RouterError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return policy.model_dump(mode="json")


@router.get("/{agent_name}")
async def get_policy(
    agent_name: str,
    _claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> dict:
    p = await Router(db).get_policy(agent_name)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no policy registered")
    return p.model_dump(mode="json")
