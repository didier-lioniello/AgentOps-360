"""Invoke endpoint — the request-path everything else supports."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import authenticate
from api.deps import enforce_rate_limit, get_db, get_redis
from core.invoker import InvocationError, Invoker
from core.router import Router, RouterError
from models.invocation import InvocationRequest, InvocationResult

router = APIRouter()


@router.post("", response_model=InvocationResult)
async def invoke(
    req: InvocationRequest,
    claims: dict = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
) -> InvocationResult:
    tenant_id = claims["tenant_id"]
    redis = get_redis()
    await enforce_rate_limit(tenant_id, redis)

    if req.version:
        version = req.version
    else:
        try:
            version = await Router(db).resolve(req.agent, sticky_key=tenant_id)
        except RouterError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    try:
        return await Invoker(db).invoke(tenant_id, req, version)
    except InvocationError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
