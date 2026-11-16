# =============================================================================
# 파일   : app/models/fms_batch.py
# 역할   : fms_batches — 팀원 FMS 묶음 하나를 실제 OMX로 싣는 진행 (2026-10-27, FMS API v1 연동 2단계)
# 작성일 : 2026-10-27
# 구성   :
#   - FmsBatch  FMS batch_id·로봇 번호, OMX에 보낼 색깔별 개수(blue·green), 단계(enums.FmsBatchStep), OMX request_id, 시각들
# 묶음 하나 = OMX 한 바퀴: /command {"blue": N, "green": N}(집기) → OMX가 양팔로 들고 대기 → FMS ready → Pinky 정밀 주차
# → /pinky(내려놓기) → 시작 자세 → FMS loaded. 들고 있는 동안 다른 묶음의 /command를 보내지 않는다(팀원 OMX는 이때도 받아 버린다)
# =============================================================================
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import FmsBatchStep, check_values


class FmsBatch(Base):
    """FMS 묶음 하나의 OMX 적재 진행. batch_id는 FMS를 다시 켜면 b-1부터 다시라 UNIQUE가 아니다(가장 나중 행을 쓴다)."""

    __tablename__ = "fms_batches"
    __table_args__ = (
        CheckConstraint(f"step IN ({check_values(FmsBatchStep)})", name="ck_fms_batches_step"),
        CheckConstraint("blue_count >= 0 AND green_count >= 0 AND blue_count + green_count >= 1", name="ck_fms_batches_counts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)   # FMS b-5
    fms_robot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    blue_count: Mapped[int] = mapped_column(Integer, nullable=False)    # 약품 수 (파란 거즈)
    green_count: Mapped[int] = mapped_column(Integer, nullable=False)   # 비품 수 (녹색 거즈)
    step: Mapped[str] = mapped_column(String(16), nullable=False)
    omx_request_id: Mapped[str | None] = mapped_column(String(64))   # emr-b{id} — /command·/pinky·완료 신호에 같은 값
    error: Mapped[str | None] = mapped_column(String(255))            # step = failed일 때 까닭
    ready_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    at_pharmacy_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # FMS robot_at_pharmacy (정밀 주차 끝)
    loaded_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    step_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
