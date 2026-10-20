# =============================================================================
# 파일   : app/api/v1/nurses.py
# 역할   : 간호사 관리 엔드포인트 (/nurses)
# 작성일 : 2026-10-14
# 구성   :
#   - list/get                    로그인한 간호사 누구나
#   - create/update/delete        관리자만
#   - reset_password              관리자만 — 다른 간호사 비밀번호를 임시 값으로
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import ADMIN_RESPONSES, DB, CurrentAdmin, get_current_admin, get_current_nurse
from app.schemas.nurse import NurseCreate, NurseOut, NurseUpdate, PasswordReset
from app.services.nurse import NurseService

router = APIRouter(dependencies=[Depends(get_current_nurse)], responses={401: {"description": "토큰 없음·만료·비활성 간호사"}})  # 전 엔드포인트 로그인 필수
NOT_FOUND_RESPONSE = {404: {"description": "간호사 없음"}}


@router.get("", response_model=list[NurseOut], summary="간호사 목록", description="비활성(`is_active=false`) 간호사도 포함.")
def list_nurses(db: DB, limit: int = Query(100, le=500), offset: int = 0) -> list[NurseOut]:
    """
    [입력] limit / offset
    [출력] list[NurseOut]
    """
    return [NurseOut.model_validate(nurse) for nurse in NurseService(db).list(limit, offset)]


@router.get("/{nurse_id}", response_model=NurseOut, summary="간호사 단건", responses=NOT_FOUND_RESPONSE)
def get_nurse(db: DB, nurse_id: int) -> NurseOut:
    """
    [입력] nurse_id
    [출력] NurseOut
    """
    return NurseOut.model_validate(NurseService(db).get(nurse_id))


@router.post(
    "", response_model=NurseOut, status_code=status.HTTP_201_CREATED,
    summary="간호사 등록 (관리자)",
    description="`employee_no` 중복이면 409. `role` 생략 시 일반 간호사. `aruco_marker_id`(0~49)가 다른 간호사와 겹치면 409.",
    dependencies=[Depends(get_current_admin)],
    responses={**ADMIN_RESPONSES, 409: {"description": "employee_no 중복·마커 번호 중복"}},
)
def create_nurse(db: DB, data: NurseCreate) -> NurseOut:
    """
    [입력] data
    [출력] NurseOut
    """
    return NurseOut.model_validate(NurseService(db).create(data))


@router.patch(
    "/{nurse_id}", response_model=NurseOut,
    summary="간호사 편집 (관리자)",
    description=(
        "보낸 필드만 바뀐다. `is_active=true`로 비활성 간호사를 복귀시킨다. "
        "자기 자신은 비활성화하거나 관리자에서 내릴 수 없다(409). "
        "`aruco_marker_id`는 `null`로 배정을 해제하고, 다른 간호사와 겹치면 409. 다른 필드의 `null`은 무시."
    ),
    responses={**NOT_FOUND_RESPONSE, **ADMIN_RESPONSES, 409: {"description": "자기 자신 비활성화·관리자 해제·마커 번호 중복"}},
)
def update_nurse(db: DB, actor: CurrentAdmin, nurse_id: int, data: NurseUpdate) -> NurseOut:
    """
    [입력] nurse_id / data: 부분 / actor: 요청한 관리자
    [출력] NurseOut
    """
    return NurseOut.model_validate(NurseService(db).update(nurse_id, data, actor.id))


@router.delete(
    "/{nurse_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="간호사 삭제 (비활성화, 관리자)",
    description="is_active=false로 표시만 한다. 행은 남고 조회에 계속 나온다. 자기 자신은 비활성화할 수 없다(409).",
    responses={**NOT_FOUND_RESPONSE, **ADMIN_RESPONSES, 409: {"description": "자기 자신 비활성화"}},
)
def delete_nurse(db: DB, actor: CurrentAdmin, nurse_id: int) -> None:
    """
    [입력] nurse_id / actor: 요청한 관리자
    [출력] 없음 (204)
    """
    NurseService(db).delete(nurse_id, actor.id)


@router.post(
    "/{nurse_id}/password-reset", status_code=status.HTTP_204_NO_CONTENT,
    summary="비밀번호 초기화 (관리자)",
    description="다른 간호사의 비밀번호를 임시 값으로 바꾼다. 간호사는 그 값으로 로그인한 뒤 `POST /auth/password`로 다시 바꾼다.",
    dependencies=[Depends(get_current_admin)],
    responses={**NOT_FOUND_RESPONSE, **ADMIN_RESPONSES},
)
def reset_password(db: DB, nurse_id: int, data: PasswordReset) -> None:
    """
    [입력] nurse_id / data.new_password
    [출력] 없음 (204)
    """
    NurseService(db).reset_password(nurse_id, data.new_password)
