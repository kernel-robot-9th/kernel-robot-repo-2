# =============================================================================
# 파일   : app/services/fms_omx.py
# 역할   : FMS 묶음을 실제 OMX(로봇팔)로 싣는다 — 집기·FMS ready·Pinky에 놓기·FMS loaded (2026-10-27, FMS API v1 연동 2단계)
# 작성일 : 2026-10-27
# 구성   :
#   - FmsOmxRunner    run_round() — 진행 중 묶음(fms_batches)마다 단계 하나씩 (app/main.py 주기 작업이 FMS_OMX_ROUND_SECONDS마다)
#   - run_omx_round() 주기 작업용: 세션을 열어 한 회차 → commit (실패하면 rollback 후 로그)
# 사용자 결정(2026-10-27): 명령은 POST /command {"command": {"blue": N, "green": N}, "request_id"} — 묶음 하나에 한 번,
#   양팔 탑재까지 실제(/pinky = Pinky 정밀 주차 뒤 내려놓기).
# 묶음 하나: /command(집기) → OMX가 끝나면 스스로 양팔로 들고 대기 → FMS ready → Pinky 정밀 주차(robot_at_pharmacy)
#   → /pinky(내려놓기) → OMX 시작 자세(pinky = completed) → FMS loaded.
# 안전: OMX가 running·grabbing·holding·releasing·returning이면 /command를 보내지 않는다 — 팀원 OMX는 들고 있는 동안에도
#   /command를 받아 왼팔을 움직인다(vision 47bcb47 코드 확인). OMX는 한 번에 묶음 하나만 쓴다.
# OMX가 명령 양식을 받지 않으면(422 — 10-28 실제 OMX는 문장만) OMX 적재를 생략한다(사용자 "OMX 양식이 없으면 생략"):
#   ready를 바로 보내고, 정밀 주차 뒤 /pinky 없이 loaded. 생략한 묶음은 omx_request_id가 비어 있고 error에 까닭을 남긴다.
# 끝났는지는 OMX GET /status로 본다(완료 신호 end-point는 로그 — OMX가 EMR에 닿지 못해도 흐름이 선다). 바깥 HTTP는 이 주기 작업에서만.
# 계약: docs/api_contract_delivery_2026-10-20.md 10.4
# =============================================================================
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.fms import FmsRejected, FmsUnavailable, batch_step, get_batch
from app.clients.omx import OmxRejected, OmxUnavailable, get_status, send_command, send_pinky
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.enums import FmsBatchStep
from app.models.fms_batch import FmsBatch
from app.services.omx_items import omx_command

log = structlog.get_logger(__name__)

FMS_OMX_LOCK_KEY = 20261028   # 회차 잠금 키 (fms_order.py의 보내기 잠금과 다른 값)
# OMX를 쓰고 있는 단계 — 이 묶음이 끝날 때까지 다른 묶음은 /command를 보내지 않는다 (READY·CALLED·PINKY = 들고 대기 중)
OMX_OWNER_STEPS = (FmsBatchStep.PICKING, FmsBatchStep.READY, FmsBatchStep.CALLED, FmsBatchStep.PINKY, FmsBatchStep.LOADING)
ACTIVE_STEPS = (*OMX_OWNER_STEPS, FmsBatchStep.PICK, FmsBatchStep.LOADED)
# OMX /status의 pinky가 이 값이면 팔이 움직이거나 물품을 들고 있다
OMX_ARM_BUSY = ("grabbing", "holding", "releasing", "returning")
OMX_PINKY_FAILED = ("grab_failed", "release_failed", "return_failed")


class FmsOmxRunner:
    """한 회차 = 한 트랜잭션(commit은 부르는 쪽). 묶음마다 많아야 단계 하나를 넘긴다."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def run_round(self, now: datetime) -> None:
        """한 회차.
        [입력] now
        [출력] 없음 (FMS·OMX 연동이 꺼져 있거나 다른 회차가 돌고 있으면 아무것도 하지 않는다)
        """
        if not (settings.FMS_BASE_URL and settings.FMS_OMX_ENABLED):
            return
        if not self.db.scalar(select(func.pg_try_advisory_xact_lock(FMS_OMX_LOCK_KEY))):
            return
        batches = list(self.db.scalars(
            select(FmsBatch).where(FmsBatch.step.in_(ACTIVE_STEPS)).order_by(FmsBatch.id).with_for_update(),
        ))
        uses_omx = [batch for batch in batches if not self._omx_skipped(batch)]
        owner = next((batch for batch in uses_omx if batch.step in OMX_OWNER_STEPS), None) \
            or next((batch for batch in uses_omx if batch.step == FmsBatchStep.PICK), None)
        for batch in batches:
            if batch.step == FmsBatchStep.LOADED:
                self._send_loaded(batch, now)
            elif batch is owner or self._omx_skipped(batch):   # 생략한 묶음은 OMX를 쓰지 않으니 기다리지 않는다
                self._advance_owner(batch, now)

    # ---- 단계 ------------------------------------------------------------------

    def _advance_owner(self, batch: FmsBatch, now: datetime) -> None:
        """OMX를 쓰는 묶음의 단계 하나.
        [입력] batch / now [출력] 없음
        """
        step = batch.step
        if step == FmsBatchStep.PICK:
            self._send_pick(batch, now)
        elif step == FmsBatchStep.PICKING:
            self._check_picked(batch, now)
        elif step == FmsBatchStep.READY:
            self._send_ready(batch, now)
        elif step == FmsBatchStep.CALLED and batch.at_pharmacy_at is not None:
            self._move(batch, self._after_pharmacy(batch), now)
        elif step == FmsBatchStep.PINKY:
            self._send_pinky(batch, now)
        elif step == FmsBatchStep.LOADING:
            self._check_loaded(batch, now)

    def _send_pick(self, batch: FmsBatch, now: datetime) -> None:
        """집기 /command {"blue": N, "green": N}. OMX가 움직이거나 들고 있으면 기다린다.
        [입력] batch: step = pick / now [출력] 없음
        """
        status = self._omx_status(batch)
        if status is None or status.get("state") == "running" or status.get("pinky") in OMX_ARM_BUSY:
            return
        counts = {"blue": batch.blue_count, "green": batch.green_count}
        request_id = f"emr-b{batch.id}"
        try:
            send_command(settings.OMX_BASE_URL, omx_command(counts), request_id, settings.OMX_TIMEOUT_SECONDS)
        except OmxUnavailable as error:
            log.warning("fms_omx_unavailable", batch_id=batch.batch_id, step=batch.step, error=str(error))
            return
        except OmxRejected as error:
            if error.status_code == 422:   # OMX가 이 명령 양식을 받지 않음 → OMX 적재 생략 (10-28 사용자)
                batch.error = f"omx skipped: /command 422 {error.detail}"[:255]
                log.warning("fms_omx_skipped", batch_id=batch.batch_id, reason="omx_command_format_not_supported",
                            command_format=settings.OMX_COMMAND_FORMAT)
                self._move(batch, FmsBatchStep.READY, now)
                return
            self._fail(batch, f"/command rejected {error.status_code}: {error.detail}", now)
            return
        batch.omx_request_id = request_id
        log.info("fms_omx_pick_sent", batch_id=batch.batch_id, request_id=request_id, blue=batch.blue_count, green=batch.green_count,
                 command_format=settings.OMX_COMMAND_FORMAT)
        self._move(batch, FmsBatchStep.PICKING, now)

    def _check_picked(self, batch: FmsBatch, now: datetime) -> None:
        """집기가 끝났는지 — OMX가 이 request_id로 completed이고 양팔로 들기 시작(grabbing·holding)했으면 다음.
        [입력] batch: step = picking / now [출력] 없음
        """
        status = self._omx_status(batch)
        if status is None or status.get("request_id") != batch.omx_request_id:
            return
        if status.get("state") == "failed":
            self._fail(batch, f"pick failed: {status.get('error')}", now)
        elif status.get("pinky") in OMX_PINKY_FAILED:
            self._fail(batch, f"grab failed: {status.get('pinky_error')}", now)
        elif status.get("state") == "completed" and status.get("pinky") in ("grabbing", "holding"):
            log.info("fms_omx_picked", batch_id=batch.batch_id, request_id=batch.omx_request_id, pinky=status.get("pinky"))
            self._move(batch, FmsBatchStep.READY, now)

    def _send_ready(self, batch: FmsBatch, now: datetime) -> None:
        """OMX가 집어서 들었다 → FMS ready (Pinky를 약제실로).
        [입력] batch: step = ready / now [출력] 없음
        """
        if not self._fms_step(batch, "ready", now):
            return
        batch.ready_sent_at = now
        self._move(batch, self._after_pharmacy(batch) if batch.at_pharmacy_at is not None else FmsBatchStep.CALLED, now)

    def _send_pinky(self, batch: FmsBatch, now: datetime) -> None:
        """Pinky 정밀 주차 끝 → /pinky (들고 있는 물품을 Pinky 위에 내려놓기).
        [입력] batch: step = pinky / now [출력] 없음
        """
        try:
            response = send_pinky(settings.OMX_BASE_URL, batch.omx_request_id or "", settings.OMX_TIMEOUT_SECONDS)
        except OmxUnavailable as error:
            log.warning("fms_omx_unavailable", batch_id=batch.batch_id, step=batch.step, error=str(error))
            return
        except OmxRejected as error:
            self._fail(batch, f"/pinky rejected {error.status_code}: {error.detail}", now)
            return
        log.info("fms_omx_pinky_sent", batch_id=batch.batch_id, request_id=batch.omx_request_id, accepted=response.get("accepted"))
        self._move(batch, FmsBatchStep.LOADING, now)

    def _check_loaded(self, batch: FmsBatch, now: datetime) -> None:
        """내려놓기가 끝났는지 — pinky = completed(시작 자세까지 돌아옴)면 다 실은 것 → FMS loaded 차례.
        [입력] batch: step = loading / now [출력] 없음
        """
        status = self._omx_status(batch)
        if status is None or status.get("request_id") != batch.omx_request_id:
            return
        if status.get("pinky") in OMX_PINKY_FAILED:
            self._fail(batch, f"load failed: {status.get('pinky')} {status.get('pinky_error')}", now)
        elif status.get("pinky") == "completed":
            log.info("fms_omx_put_down", batch_id=batch.batch_id, request_id=batch.omx_request_id)
            self._move(batch, FmsBatchStep.LOADED, now)

    def _send_loaded(self, batch: FmsBatch, now: datetime) -> None:
        """다 실었다 → FMS loaded (Pinky가 병실로).
        FMS 묶음이 아직 at_pharmacy가 아니면(called — FMS의 Pinky가 아직 오는 중) 기다린다: 실물 Pinky 신호로 먼저 실었을 때
        loaded를 보내면 FMS가 409 bad_batch_state를 주고 '이미 넘어감'으로 잘못 보이기 때문 (2026-10-28)
        [입력] batch: step = loaded / now [출력] 없음
        """
        try:
            fms_status = get_batch(settings.FMS_BASE_URL, batch.batch_id, settings.FMS_TIMEOUT_SECONDS).get("status")
        except FmsUnavailable as error:
            log.warning("fms_unavailable", batch_id=batch.batch_id, step="loaded", error=str(error))
            return
        except FmsRejected as error:
            self._fail(batch, f"FMS batch {batch.batch_id} lookup rejected {error.status_code} {error.code}", now)
            return
        if fms_status in ("assigned", "called"):
            return   # FMS의 Pinky가 약제실에 오면 다음 회차에
        if not self._fms_step(batch, "loaded", now):
            return
        batch.loaded_sent_at = now
        self._move(batch, FmsBatchStep.DELIVERING, now)

    # ---- 내부 ------------------------------------------------------------------

    @staticmethod
    def _omx_skipped(batch: FmsBatch) -> bool:
        """OMX 적재를 생략한 묶음인지 — /command가 422로 거절돼 OMX 작업이 없다.
        [입력] batch [출력] bool
        """
        return batch.omx_request_id is None and batch.step in (FmsBatchStep.READY, FmsBatchStep.CALLED)

    @staticmethod
    def _after_pharmacy(batch: FmsBatch) -> FmsBatchStep:
        """정밀 주차 뒤 다음 단계 — OMX가 들고 있으면 내려놓기(/pinky), 생략했으면 바로 loaded.
        [입력] batch [출력] FmsBatchStep
        """
        return FmsBatchStep.LOADED if batch.omx_request_id is None else FmsBatchStep.PINKY

    def _omx_status(self, batch: FmsBatch) -> dict[str, Any] | None:
        """OMX GET /status. 응답이 없으면 None(다음 회차에 다시).
        [입력] batch: 로그용 [출력] dict | None
        """
        try:
            return get_status(settings.OMX_BASE_URL, settings.OMX_TIMEOUT_SECONDS)
        except (OmxUnavailable, OmxRejected) as error:
            log.warning("fms_omx_unavailable", batch_id=batch.batch_id, step=batch.step, error=str(error))
            return None

    def _fms_step(self, batch: FmsBatch, step: str, now: datetime) -> bool:
        """FMS ready·loaded. 409 bad_batch_state는 '이미 넘어감'(10-27 사용자 결정).
        [입력] batch / step: "ready" | "loaded" / now
        [출력] bool: 보냈거나 이미 넘어갔으면 True (응답 없음이면 False — 다음 회차에 다시, 거절이면 failed)
        """
        try:
            response = batch_step(settings.FMS_BASE_URL, batch.batch_id, step, settings.FMS_TIMEOUT_SECONDS)
        except FmsUnavailable as error:
            log.warning("fms_unavailable", batch_id=batch.batch_id, step=step, error=str(error))
            return False
        except FmsRejected as error:
            self._fail(batch, f"FMS {step} rejected {error.status_code} {error.code}: {error.message}", now)
            return False
        log.info(f"fms_{step}_sent", batch_id=batch.batch_id, already=bool(response.get("already")), fms_status=response.get("status"))
        return True

    @staticmethod
    def _move(batch: FmsBatch, step: FmsBatchStep, now: datetime) -> None:
        """단계 바꾸기.
        [입력] batch / step / now [출력] 없음
        """
        batch.step = step
        batch.step_changed_at = now

    def _fail(self, batch: FmsBatch, reason: str, now: datetime) -> None:
        """멈춤 — 사람이 봐야 한다(로봇팔·Pinky 상태 확인). 배송 상태는 바꾸지 않는다(1단계 이벤트 처리 몫).
        [입력] batch / reason / now [출력] 없음
        """
        batch.error = reason[:255]
        log.error("fms_omx_failed", batch_id=batch.batch_id, step=batch.step, request_id=batch.omx_request_id, reason=reason)
        self._move(batch, FmsBatchStep.FAILED, now)


def run_omx_round() -> None:
    """주기 작업 한 회차 — 자기 세션으로 돌고 commit. 예외는 로그만 남기고 다음 회차로.
    [입력] 없음
    [출력] 없음
    """
    with SessionLocal() as db:
        try:
            FmsOmxRunner(db).run_round(datetime.now(UTC))
            db.commit()
        except Exception:   # 주기 작업이 죽지 않게 — 원인은 로그로
            db.rollback()
            log.exception("fms_omx_round_failed")
