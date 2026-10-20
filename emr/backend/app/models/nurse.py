# =============================================================================
# 파일   : app/models/nurse.py
# 역할   : nurses — 간호사
# 작성일 : 2026-10-13
# 구성   :
#   - Nurse  역할(admin·nurse)은 String + CHECK
#            aruco_marker_id: 신분증 대신 쓰는 ArUco 마커 번호 (DICT_4X4_50, 0~49, 중복 불가) — 2026-10-16
# =============================================================================
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import NurseRole, check_values

ARUCO_MARKER_ID_MAX = 49  # DICT_4X4_50 사전의 마커는 0~49 (50개)


class Nurse(TimestampMixin, Base):
    """간호사. 사번·비밀번호로 로그인하는 사용자."""

    __tablename__ = "nurses"
    __table_args__ = (
        CheckConstraint(f"role IN ({check_values(NurseRole)})", name="ck_nurses_role"),
        CheckConstraint(f"aruco_marker_id BETWEEN 0 AND {ARUCO_MARKER_ID_MAX}", name="ck_nurses_aruco_marker_id"),
        UniqueConstraint("aruco_marker_id", name="uq_nurses_aruco_marker_id"),  # NULL은 여러 행 허용
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # 사번 (로그인 ID)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)  # bcrypt. *Out 스키마에 절대 노출 금지
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # 퇴사·휴직 시 False (삭제 안 함)
    role: Mapped[str] = mapped_column(String(16), default=NurseRole.NURSE, nullable=False)  # admin | nurse
    aruco_marker_id: Mapped[int | None] = mapped_column(Integer)  # ArUco DICT_4X4_50 마커 번호. NULL=미배정
