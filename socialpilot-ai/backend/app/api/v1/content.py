# NOTE: deliberately no `from __future__ import annotations` here — combined
# with slowapi's `@limiter.limit(...)` decorator on the generate endpoints,
# postponed evaluation of annotations breaks FastAPI's ability to tell a
# Pydantic body model apart from a query param (see app/api/v1/auth.py for
# the same note; this bit us for real in Phase 1).
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_org_member, require_role
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.models.organization_member import CONTENT_ROLES, OrganizationMember
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.content import (
    ContentGenerationPublic,
    ContentItemCreate,
    ContentItemPublic,
    ContentItemStatus,
    ContentItemUpdate,
    ContentPillarCreate,
    ContentPillarPublic,
    ContentPillarUpdate,
    ContentStrategyCreate,
    ContentStrategyPublic,
    ContentStrategyUpdate,
    GenerateIdeasRequest,
    GeneratePostRequest,
)
from app.services.ai import get_ai_provider
from app.services.content_generation_service import ContentGenerationService
from app.services.content_item_service import ContentItemService
from app.services.content_strategy_service import ContentStrategyService

router = APIRouter(prefix="/organizations/{organization_id}/content", tags=["content"])
settings = get_settings()


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #

@router.post("/strategies", response_model=ContentStrategyPublic, status_code=201)
async def create_strategy(
    organization_id: uuid.UUID,
    payload: ContentStrategyCreate,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ContentStrategyPublic:
    strategy = await ContentStrategyService(db).create(organization_id=organization_id, payload=payload)
    await AuditLogRepository(db).record(
        action="content.strategy.created", organization_id=organization_id,
        user_id=member.user_id, resource_type="content_strategy", resource_id=str(strategy.id),
    )
    return ContentStrategyPublic.model_validate(strategy)


@router.get("/strategies", response_model=list[ContentStrategyPublic])
async def list_strategies(
    organization_id: uuid.UUID,
    member: OrganizationMember = Depends(require_org_member()),
    db: AsyncSession = Depends(get_db),
) -> list[ContentStrategyPublic]:
    strategies = await ContentStrategyService(db).list_for_org(organization_id)
    return [ContentStrategyPublic.model_validate(s) for s in strategies]


@router.get("/strategies/{strategy_id}", response_model=ContentStrategyPublic)
async def get_strategy(
    organization_id: uuid.UUID,
    strategy_id: uuid.UUID,
    member: OrganizationMember = Depends(require_org_member()),
    db: AsyncSession = Depends(get_db),
) -> ContentStrategyPublic:
    strategy = await ContentStrategyService(db).get_or_raise(strategy_id=strategy_id, organization_id=organization_id)
    return ContentStrategyPublic.model_validate(strategy)


@router.patch("/strategies/{strategy_id}", response_model=ContentStrategyPublic)
async def update_strategy(
    organization_id: uuid.UUID,
    strategy_id: uuid.UUID,
    payload: ContentStrategyUpdate,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ContentStrategyPublic:
    service = ContentStrategyService(db)
    strategy = await service.get_or_raise(strategy_id=strategy_id, organization_id=organization_id)
    strategy = await service.update(strategy, payload=payload)
    return ContentStrategyPublic.model_validate(strategy)


@router.delete("/strategies/{strategy_id}", status_code=204, response_model=None)
async def delete_strategy(
    organization_id: uuid.UUID,
    strategy_id: uuid.UUID,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ContentStrategyService(db)
    strategy = await service.get_or_raise(strategy_id=strategy_id, organization_id=organization_id)
    await service.delete(strategy)
    await AuditLogRepository(db).record(
        action="content.strategy.deleted", organization_id=organization_id,
        user_id=member.user_id, resource_type="content_strategy", resource_id=str(strategy_id),
    )


# --------------------------------------------------------------------------- #
# Pillars
# --------------------------------------------------------------------------- #

@router.post("/strategies/{strategy_id}/pillars", response_model=ContentPillarPublic, status_code=201)
async def create_pillar(
    organization_id: uuid.UUID,
    strategy_id: uuid.UUID,
    payload: ContentPillarCreate,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ContentPillarPublic:
    service = ContentStrategyService(db)
    strategy = await service.get_or_raise(strategy_id=strategy_id, organization_id=organization_id)
    pillar = await service.add_pillar(strategy=strategy, organization_id=organization_id, payload=payload)
    return ContentPillarPublic.model_validate(pillar)


@router.get("/strategies/{strategy_id}/pillars", response_model=list[ContentPillarPublic])
async def list_pillars(
    organization_id: uuid.UUID,
    strategy_id: uuid.UUID,
    member: OrganizationMember = Depends(require_org_member()),
    db: AsyncSession = Depends(get_db),
) -> list[ContentPillarPublic]:
    pillars = await ContentStrategyService(db).list_pillars(strategy_id=strategy_id, organization_id=organization_id)
    return [ContentPillarPublic.model_validate(p) for p in pillars]


@router.patch("/pillars/{pillar_id}", response_model=ContentPillarPublic)
async def update_pillar(
    organization_id: uuid.UUID,
    pillar_id: uuid.UUID,
    payload: ContentPillarUpdate,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ContentPillarPublic:
    service = ContentStrategyService(db)
    pillar = await service.get_pillar_or_raise(pillar_id=pillar_id, organization_id=organization_id)
    pillar = await service.update_pillar(pillar, payload=payload)
    return ContentPillarPublic.model_validate(pillar)


@router.delete("/pillars/{pillar_id}", status_code=204, response_model=None)
async def delete_pillar(
    organization_id: uuid.UUID,
    pillar_id: uuid.UUID,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ContentStrategyService(db)
    pillar = await service.get_pillar_or_raise(pillar_id=pillar_id, organization_id=organization_id)
    await service.delete_pillar(pillar)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #

@router.post("/generate/ideas", response_model=ContentGenerationPublic)
@limiter.limit(settings.ai_generation_rate_limit)
async def generate_ideas(
    request: Request,
    organization_id: uuid.UUID,
    payload: GenerateIdeasRequest,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
    ai_provider=Depends(get_ai_provider),
) -> ContentGenerationPublic:
    strategy_service = ContentStrategyService(db)
    strategy = await strategy_service.get_or_raise(strategy_id=payload.strategy_id, organization_id=organization_id)

    # get_ai_provider() raises ConfigurationError (-> 503, see app/main.py) when
    # AI_API_KEY isn't set — propagates untouched, no fake/degraded response.
    # Injected via Depends() (not called directly) so tests can override it
    # with a deterministic fake provider — see tests/integration/test_content_generation.py.
    generation_service = ContentGenerationService(db, ai_provider=ai_provider)
    generation, _result = await generation_service.generate_ideas(
        organization_id=organization_id, user_id=member.user_id, strategy=strategy, request=payload,
    )
    await AuditLogRepository(db).record(
        action="content.generation.ideas", organization_id=organization_id,
        user_id=member.user_id, resource_type="content_generation", resource_id=str(generation.id),
        metadata={"strategy_id": str(strategy.id), "status": generation.status.value},
    )
    return ContentGenerationPublic.model_validate(generation)


@router.post("/generate/post", response_model=ContentGenerationPublic)
@limiter.limit(settings.ai_generation_rate_limit)
async def generate_post(
    request: Request,
    organization_id: uuid.UUID,
    payload: GeneratePostRequest,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
    ai_provider=Depends(get_ai_provider),
) -> ContentGenerationPublic:
    strategy_service = ContentStrategyService(db)
    strategy = await strategy_service.get_or_raise(strategy_id=payload.strategy_id, organization_id=organization_id)

    generation_service = ContentGenerationService(db, ai_provider=ai_provider)
    generation, _result = await generation_service.generate_post(
        organization_id=organization_id, user_id=member.user_id, strategy=strategy, request=payload,
    )
    await AuditLogRepository(db).record(
        action="content.generation.post", organization_id=organization_id,
        user_id=member.user_id, resource_type="content_generation", resource_id=str(generation.id),
        metadata={"strategy_id": str(strategy.id), "status": generation.status.value},
    )
    return ContentGenerationPublic.model_validate(generation)


# --------------------------------------------------------------------------- #
# Items (library)
# --------------------------------------------------------------------------- #

@router.post("/items", response_model=ContentItemPublic, status_code=201)
async def create_item(
    organization_id: uuid.UUID,
    payload: ContentItemCreate,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ContentItemPublic:
    item = await ContentItemService(db).create(organization_id=organization_id, user_id=member.user_id, payload=payload)
    await AuditLogRepository(db).record(
        action="content.item.saved", organization_id=organization_id,
        user_id=member.user_id, resource_type="content_item", resource_id=str(item.id),
    )
    return ContentItemPublic.model_validate(item)


@router.get("/items", response_model=list[ContentItemPublic])
async def list_items(
    organization_id: uuid.UUID,
    platform: str | None = None,
    status: ContentItemStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    member: OrganizationMember = Depends(require_org_member()),
    db: AsyncSession = Depends(get_db),
) -> list[ContentItemPublic]:
    items = await ContentItemService(db).list_for_org(
        organization_id, platform=platform, status=status.value if status else None,
        limit=limit, offset=offset,
    )
    return [ContentItemPublic.model_validate(i) for i in items]


@router.get("/items/{item_id}", response_model=ContentItemPublic)
async def get_item(
    organization_id: uuid.UUID,
    item_id: uuid.UUID,
    member: OrganizationMember = Depends(require_org_member()),
    db: AsyncSession = Depends(get_db),
) -> ContentItemPublic:
    item = await ContentItemService(db).get_or_raise(item_id=item_id, organization_id=organization_id)
    return ContentItemPublic.model_validate(item)


@router.patch("/items/{item_id}", response_model=ContentItemPublic)
async def update_item(
    organization_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ContentItemUpdate,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ContentItemPublic:
    service = ContentItemService(db)
    item = await service.get_or_raise(item_id=item_id, organization_id=organization_id)
    item = await service.update(item, payload=payload)
    return ContentItemPublic.model_validate(item)


@router.delete("/items/{item_id}", status_code=204, response_model=None)
async def delete_item(
    organization_id: uuid.UUID,
    item_id: uuid.UUID,
    member: OrganizationMember = Depends(require_role(*CONTENT_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ContentItemService(db)
    item = await service.get_or_raise(item_id=item_id, organization_id=organization_id)
    await service.delete(item)
    await AuditLogRepository(db).record(
        action="content.item.deleted", organization_id=organization_id,
        user_id=member.user_id, resource_type="content_item", resource_id=str(item_id),
    )
