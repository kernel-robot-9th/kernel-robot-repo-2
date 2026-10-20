# =============================================================================
# 파일   : app/repositories/nurse.py
# 역할   : 간호사 조회
# 작성일 : 2026-10-13
# 구성   :
#   - NurseRepository  사번 조회, 마커 번호 조회
# =============================================================================
from __future__ import annotations

from sqlalchemy import select

from app.models.nurse import Nurse
from app.repositories.base import BaseRepository


class NurseRepository(BaseRepository[Nurse]):
    """nurses 조회."""

    model = Nurse

    def get_by_employee_no(self, employee_no: str) -> Nurse | None:
        """사번으로 조회.
        [입력] employee_no
        [출력] Nurse | None
        """
        return self.db.scalar(select(Nurse).where(Nurse.employee_no == employee_no))

    def get_by_aruco_marker_id(self, aruco_marker_id: int) -> Nurse | None:
        """마커 번호로 조회 (배정 시 중복 검사).
        [입력] aruco_marker_id
        [출력] Nurse | None
        """
        return self.db.scalar(select(Nurse).where(Nurse.aruco_marker_id == aruco_marker_id))
