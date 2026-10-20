# =============================================================================
# 파일   : app/services/nurse.py
# 역할   : 간호사 관리
# 작성일 : 2026-10-14
# 구성   :
#   - NurseService  list/get/create/update/delete/reset_password — 마커 번호 중복 검사 포함
# 권한(관리자만 등록·편집·비활성화·초기화)은 라우터의 CurrentAdmin이 막는다. 여기서는 자기 자신 보호만 한다
# =============================================================================
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, NotFound
from app.core.security import hash_password
from app.models.enums import NurseRole
from app.models.nurse import Nurse
from app.repositories.nurse import NurseRepository
from app.schemas.nurse import NurseCreate, NurseUpdate

NULLABLE_UPDATE_FIELDS = frozenset({"aruco_marker_id"})  # PATCH에서 null로 지울 수 있는 필드. 나머지 null은 무시


class NurseService:
    """간호사 관리 — 등록·편집·조회·비활성화·비밀번호 초기화. 행은 지우지 않는다."""

    def __init__(self, db: Session) -> None:
        self.repo = NurseRepository(db)

    def list(self, limit: int = 100, offset: int = 0) -> list[Nurse]:
        """간호사 목록.
        [입력] limit / offset
        [출력] list[Nurse]: id 순
        """
        return self.repo.list(limit, offset)

    def get(self, nurse_id: int) -> Nurse:
        """한 건 조회.
        [입력] nurse_id
        [출력] Nurse (없으면 NotFound)
        """
        nurse = self.repo.get(nurse_id)
        if nurse is None:
            raise NotFound(f"nurse {nurse_id} not found", code="nurse_not_found")
        return nurse

    def create(self, data: NurseCreate) -> Nurse:
        """간호사 등록. 사번 중복이면 Conflict.
        [입력] data: password는 요청으로 받은 평문 — bcrypt 해시로 바꿔 저장하고 평문은 남기지 않는다
        [출력] Nurse
        """
        if self.repo.get_by_employee_no(data.employee_no):
            raise Conflict(f"employee_no {data.employee_no} already exists", code="employee_no_duplicate")
        if data.aruco_marker_id is not None:
            self._ensure_marker_free(data.aruco_marker_id, nurse_id=None)
        return self.repo.add(Nurse(
            employee_no=data.employee_no, name=data.name, password_hash=hash_password(data.password), role=data.role,
            aruco_marker_id=data.aruco_marker_id,
        ))

    def update(self, nurse_id: int, data: NurseUpdate, actor_id: int) -> Nurse:
        """보낸 필드만 수정. null은 마커 번호에서만 '배정 해제'이고, 다른 필드의 null은 무시한다 (NOT NULL 컬럼).
        [입력] nurse_id / data / actor_id: 요청한 관리자
        [출력] Nurse (자기 자신을 비활성화하거나 관리자에서 내리면, 마커 번호가 겹치면 Conflict)
        """
        nurse = self.get(nurse_id)
        if data.is_active is False:
            self._ensure_not_self(nurse_id, actor_id)
        if data.role is not None and data.role != NurseRole.ADMIN and nurse_id == actor_id:
            # 자기 권한을 내리면 마지막 관리자가 사라져 아무도 간호사를 관리할 수 없게 될 수 있다
            raise Conflict("cannot remove your own admin role", code="self_role_change")
        changes = {
            field: value for field, value in data.model_dump(exclude_unset=True).items()
            if value is not None or field in NULLABLE_UPDATE_FIELDS
        }
        if changes.get("aruco_marker_id") is not None:
            self._ensure_marker_free(changes["aruco_marker_id"], nurse_id=nurse_id)
        for field, value in changes.items():
            setattr(nurse, field, value)
        return nurse

    def reset_password(self, nurse_id: int, raw_new_password: str) -> None:
        """비밀번호를 임시 값으로 초기화 (관리자). 비활성 간호사도 바꿀 수 있다 — 복귀 전에 미리 정해 둘 수 있게.
        [입력] nurse_id / raw_new_password: 요청으로 받은 평문 — bcrypt 해시로 바꿔 저장하고 평문은 남기지 않는다
        [출력] 없음 (없으면 NotFound)
        """
        nurse = self.get(nurse_id)
        nurse.password_hash = hash_password(raw_new_password)

    def delete(self, nurse_id: int, actor_id: int) -> None:
        """비활성화(is_active=False). 행은 남는다 — 복귀는 update로 is_active=True.
        [입력] nurse_id / actor_id: 요청한 간호사
        [출력] 없음 (자기 자신이면 Conflict)
        """
        nurse = self.get(nurse_id)
        self._ensure_not_self(nurse_id, actor_id)
        nurse.is_active = False

    def _ensure_marker_free(self, aruco_marker_id: int, nurse_id: int | None) -> None:
        """마커 번호가 다른 간호사에게 배정돼 있지 않은지 확인. 비활성 간호사의 번호도 쓰는 중으로 본다 — 해제 후 재배정.
        [입력] aruco_marker_id / nurse_id: 수정 대상 (등록이면 None)
        [출력] 없음 (다른 간호사가 쓰면 Conflict)
        """
        owner = self.repo.get_by_aruco_marker_id(aruco_marker_id)
        if owner is not None and owner.id != nurse_id:
            raise Conflict(
                f"aruco_marker_id {aruco_marker_id} is assigned to {owner.employee_no}", code="aruco_marker_duplicate",
            )

    @staticmethod
    def _ensure_not_self(nurse_id: int, actor_id: int) -> None:
        """자기 계정 비활성화 방지 — 마지막 활성 간호사가 스스로 잠그면 아무도 로그인할 수 없다.
        [입력] nurse_id / actor_id
        [출력] 없음 (같으면 Conflict)
        """
        if nurse_id == actor_id:
            raise Conflict("cannot deactivate yourself", code="self_deactivation")
