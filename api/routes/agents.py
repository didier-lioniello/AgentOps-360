"""Agent registry CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import authenticate
from api.deps import get_db
from core.registry import AgentRegistry, RegistryError
from models.agent import AgentManifest, AgentStatus

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def publish(
    manifest: AgentManifest,
    _claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> dict:
    reg = AgentRegistry(db)
    try:
        record = await reg.publish(manifest)
    except RegistryError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return record.model_dump(mode="json", by_alias=True)


@router.get("/{name}/{version}")
async def get_one(
    name: str,
    version: str,
    _claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rec = await AgentRegistry(db).get(name, version)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent version not found")
    return rec.model_dump(mode="json", by_alias=True)


@router.get("/{name}")
async def list_versions(
    name: str,
    _claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    recs = await AgentRegistry(db).list_versions(name)
    return [r.model_dump(mode="json", by_alias=True) for r in recs]


@router.get("")
async def list_agents(
    _claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    return await AgentRegistry(db).list_agents()


@router.patch("/{name}/{version}/status")
async def set_status(
    name: str,
    version: str,
    new_status: AgentStatus,
    _claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await AgentRegistry(db).set_status(name, version, new_status)
    except RegistryError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return {"name": name, "version": version, "status": new_status.value}
