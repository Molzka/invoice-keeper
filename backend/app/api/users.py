from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

from app.api.dependencies import AdminUser, DbSession, require_csrf, require_json_request
from app.models import User
from app.schemas.users import UserCreate, UserList, UserRead, UserUpdate
from app.services.users import create_user as create_user_record
from app.services.users import delete_user as delete_user_record
from app.services.users import update_user as update_user_record

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserList)
async def list_users(
    admin: AdminUser,
    db: DbSession,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserList:
    total = await db.scalar(select(func.count()).select_from(User).where(User.role == "user"))
    users = await db.scalars(
        select(User)
        .where(User.role == "user")
        .order_by(User.username, User.id)
        .limit(limit)
        .offset(offset)
    )
    response.headers["Cache-Control"] = "no-store"
    return UserList(
        items=[UserRead.model_validate(user) for user in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=UserRead,
    status_code=201,
    dependencies=[Depends(require_csrf), Depends(require_json_request)],
)
async def create_user(
    payload: UserCreate, admin: AdminUser, db: DbSession, response: Response
) -> UserRead:
    user = await create_user_record(db, payload, admin.id)
    response.headers["Cache-Control"] = "no-store"
    return UserRead.model_validate(user)


@router.delete("/{user_id}", status_code=204, dependencies=[Depends(require_csrf)])
async def delete_user(user_id: UUID, admin: AdminUser, db: DbSession) -> Response:
    await delete_user_record(db, user_id, admin.id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_csrf), Depends(require_json_request)],
)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    admin: AdminUser,
    db: DbSession,
    response: Response,
) -> UserRead:
    user = await update_user_record(db, user_id, payload, admin.id)
    response.headers["Cache-Control"] = "no-store"
    return UserRead.model_validate(user)
