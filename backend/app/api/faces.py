from __future__ import annotations

import uuid

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import file_to_response
from app.core.auth import get_current_user
from app.database import get_session
from app.models.db import AlbumFile, FaceDetection, MediaFile, Person, RootFolder, User, UserRootPref
from app.models.schemas import (
    MergePeopleRequest,
    PaginatedFiles,
    PeopleListResponse,
    PersonResponse,
    PersonUpdateRequest,
)

router = APIRouter()


async def _get_user_visible_root_ids(user: User, session: AsyncSession) -> list[uuid.UUID]:
    prefs_result = await session.execute(
        select(UserRootPref).where(UserRootPref.user_id == user.id, UserRootPref.is_visible == False)  # noqa: E712
    )
    hidden_ids = {p.root_folder_id for p in prefs_result.scalars().all()}
    roots_result = await session.execute(
        select(RootFolder.id).where(RootFolder.is_active == True)  # noqa: E712
    )
    return [rid for (rid,) in roots_result.all() if rid not in hidden_ids]


def _build_person_response(person: Person, face_count: int, sample_urls: list[str]) -> PersonResponse:
    return PersonResponse(
        id=person.id,
        name=person.name,
        face_count=face_count,
        sample_thumbnail_urls=sample_urls,
    )


@router.get("/people", response_model=PeopleListResponse)
async def list_people(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PeopleListResponse:
    """List persons visible to this user with face_count >= their threshold."""
    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if not visible_root_ids:
        return PeopleListResponse(people=[])

    min_count = current_user.face_cluster_min_size

    stmt = (
        select(Person, func.count(FaceDetection.id).label("face_count"))
        .join(FaceDetection, FaceDetection.person_id == Person.id)
        .join(MediaFile, MediaFile.id == FaceDetection.file_id)
        .where(
            MediaFile.root_folder_id.in_(visible_root_ids),
            MediaFile.is_deleted == False,  # noqa: E712
        )
        .group_by(Person.id)
        .having(func.count(FaceDetection.id) >= min_count)
        .order_by(func.count(FaceDetection.id).desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    people: list[PersonResponse] = []
    for person, face_count in rows:
        sample_stmt = (
            select(MediaFile.id)
            .join(FaceDetection, FaceDetection.file_id == MediaFile.id)
            .where(
                FaceDetection.person_id == person.id,
                MediaFile.root_folder_id.in_(visible_root_ids),
                MediaFile.is_deleted == False,  # noqa: E712
                MediaFile.thumbnail_path.isnot(None),
            )
            .limit(4)
        )
        sample_result = await session.execute(sample_stmt)
        sample_urls = [f"/api/thumbnails/{fid}" for (fid,) in sample_result.all()]
        people.append(_build_person_response(person, face_count, sample_urls))

    return PeopleListResponse(people=people)


@router.get("/people/{person_id}", response_model=PersonResponse)
async def get_person(
    person_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PersonResponse:
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    visible_root_ids = await _get_user_visible_root_ids(current_user, session)

    count_result = await session.execute(
        select(func.count(FaceDetection.id))
        .join(MediaFile, MediaFile.id == FaceDetection.file_id)
        .where(
            FaceDetection.person_id == person_id,
            MediaFile.root_folder_id.in_(visible_root_ids),
            MediaFile.is_deleted == False,  # noqa: E712
        )
    )
    face_count = count_result.scalar_one()

    sample_result = await session.execute(
        select(MediaFile.id)
        .join(FaceDetection, FaceDetection.file_id == MediaFile.id)
        .where(
            FaceDetection.person_id == person_id,
            MediaFile.root_folder_id.in_(visible_root_ids),
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.thumbnail_path.isnot(None),
        )
        .limit(4)
    )
    sample_urls = [f"/api/thumbnails/{fid}" for (fid,) in sample_result.all()]
    return _build_person_response(person, face_count, sample_urls)


@router.get("/people/{person_id}/files", response_model=PaginatedFiles)
async def get_person_files(
    person_id: uuid.UUID,
    page: int = 1,
    page_size: int = 100,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaginatedFiles:
    """Return paginated gallery of files in which this person appears."""
    visible_root_ids = await _get_user_visible_root_ids(current_user, session)

    base_stmt = (
        select(MediaFile)
        .join(FaceDetection, FaceDetection.file_id == MediaFile.id)
        .where(
            FaceDetection.person_id == person_id,
            MediaFile.root_folder_id.in_(visible_root_ids),
            MediaFile.is_deleted == False,  # noqa: E712
        )
        .distinct()
    )

    count_result = await session.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )
    total = count_result.scalar_one()

    stmt = (
        base_stmt
        .order_by(MediaFile.taken_at.desc().nullslast(), MediaFile.filename.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    files = result.scalars().all()

    return PaginatedFiles(
        items=[file_to_response(f) for f in files],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


@router.patch("/people/{person_id}", response_model=PersonResponse)
async def update_person(
    person_id: uuid.UUID,
    body: PersonUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PersonResponse:
    person = await session.get(Person, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    if body.name is not None:
        person.name = body.name.strip() or None

    await session.commit()
    await session.refresh(person)

    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    count_result = await session.execute(
        select(func.count(FaceDetection.id))
        .join(MediaFile, MediaFile.id == FaceDetection.file_id)
        .where(
            FaceDetection.person_id == person_id,
            MediaFile.root_folder_id.in_(visible_root_ids),
            MediaFile.is_deleted == False,  # noqa: E712
        )
    )
    face_count = count_result.scalar_one()

    sample_result = await session.execute(
        select(MediaFile.id)
        .join(FaceDetection, FaceDetection.file_id == MediaFile.id)
        .where(
            FaceDetection.person_id == person_id,
            MediaFile.root_folder_id.in_(visible_root_ids),
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.thumbnail_path.isnot(None),
        )
        .limit(4)
    )
    sample_urls = [f"/api/thumbnails/{fid}" for (fid,) in sample_result.all()]
    return _build_person_response(person, face_count, sample_urls)


@router.post("/people/merge", response_model=PersonResponse)
async def merge_people(
    body: MergePeopleRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PersonResponse:
    """Move all faces from source_id into target_id and delete source."""
    if body.source_id == body.target_id:
        raise HTTPException(status_code=400, detail="source and target must differ")

    target = await session.get(Person, body.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target person not found")

    source = await session.get(Person, body.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source person not found")

    await session.execute(
        update(FaceDetection)
        .where(FaceDetection.person_id == body.source_id)
        .values(person_id=body.target_id)
    )
    await session.delete(source)
    await session.flush()

    # Recompute target centroid from all its faces
    emb_result = await session.execute(
        select(FaceDetection.embedding)
        .where(FaceDetection.person_id == body.target_id, FaceDetection.embedding.isnot(None))
    )
    embeddings = [r[0] for r in emb_result.all()]
    if embeddings:
        arr = np.array(embeddings, dtype=np.float32)
        centroid = arr.mean(axis=0)
        centroid /= np.linalg.norm(centroid) + 1e-10
        target.centroid = centroid.tolist()

    await session.commit()
    await session.refresh(target)

    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    count_result = await session.execute(
        select(func.count(FaceDetection.id))
        .join(MediaFile, MediaFile.id == FaceDetection.file_id)
        .where(
            FaceDetection.person_id == body.target_id,
            MediaFile.root_folder_id.in_(visible_root_ids),
            MediaFile.is_deleted == False,  # noqa: E712
        )
    )
    face_count = count_result.scalar_one()
    sample_result = await session.execute(
        select(MediaFile.id)
        .join(FaceDetection, FaceDetection.file_id == MediaFile.id)
        .where(
            FaceDetection.person_id == body.target_id,
            MediaFile.root_folder_id.in_(visible_root_ids),
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.thumbnail_path.isnot(None),
        )
        .limit(4)
    )
    sample_urls = [f"/api/thumbnails/{fid}" for (fid,) in sample_result.all()]
    return _build_person_response(target, face_count, sample_urls)


@router.post("/cluster", status_code=202)
async def trigger_cluster(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Enqueue a face clustering job on the ML worker."""
    try:
        from arq.connections import RedisSettings, create_pool

        from app.config import settings as app_settings

        arq = await create_pool(RedisSettings.from_dsn(app_settings.redis_url))
        await arq.enqueue_job("cluster_faces")
        await arq.aclose()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not enqueue job: {exc}") from exc

    return {"message": "Clustering job enqueued"}
