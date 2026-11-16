# =============================================================================
# 파일   : app/models/enums.py
# 역할   : 상태값 Enum (varchar+CHECK 방식, PG ENUM 미사용)
# 작성일 : 2026-10-13
# 구성   :
#   - NurseRole                       간호사 역할 (관리자·일반)
#   - SupplyCategory / RequestableBy  비품 분류
#   - DeliveryStatus                  배송 상태
#   - DeliveryFailureReason           배송 실패 사유 (2026-10-20)
#   - DeliveryEventType / DeliveryEventActor  배송 기록 사건 종류·누가 (2026-10-21, 로드맵 4단계 · bedside 2026-10-22)
#   - DeliveryRequester               배송을 만든 쪽 (간호사 예약·병상 단말 환자 요청, 2026-10-22)
#   - ReceiptMethod                   수령 방법 (DB에 저장하지 않음 — Delivery.receipt_method가 계산, 2026-10-23 문자열에서 옮김)
#   - RobotType / RobotStatus         로봇 종류·상태
#   - NotificationEvent               실시간 알림 종류 (DB에 저장하지 않음, SSE event 이름)
#   - check_values()                  CHECK 제약용 IN 리스트
# =============================================================================
from __future__ import annotations

from enum import StrEnum


class NurseRole(StrEnum):
    """간호사 역할 (2026-10-15 결정). 관리자만 간호사 등록·수정·비활성화·비밀번호 초기화와
    장소·맵·로봇 등록·수정·삭제를 할 수 있다. 비품 관리·배송 예약은 모두 가능.
    """
    ADMIN = "admin"  # 관리자
    NURSE = "nurse"  # 일반 간호사


class SupplyCategory(StrEnum):
    """비품 대분류."""
    MEDICATION = "medication"
    SUPPLY = "supply"


class RequestableBy(StrEnum):
    """누가 요청할 수 있는 품목인가. 요청 기능(SR-02)이 들어올 때 서비스에서 대조한다."""
    NURSE = "nurse"
    PATIENT = "patient"


class DeliveryStatus(StrEnum):
    """배송 상태 (2026-10-20 로드맵 2단계, docs/api_contract_delivery_2026-10-20.md).
    reserved → dispatched(로봇 claim) → arrived(로봇 도착 보고, 일회용 마커 생성) → received(로봇이 일회용 마커 읽음)
    reserved → cancelled(간호사 취소) / preparing·dispatched·arrived → failed(로봇 실패 보고, 재고 복구)
    FMS 연동(2026-10-29 사용자 "OMX 적재 준비 단계 추가, 호출부터 준비, 정밀 주차 출발"):
    reserved → preparing(FMS robot_called — Pinky를 약제실로 부름, OMX 적재 준비) → dispatched(약제실 정밀 주차 끝) → arrived → received
    간호사 변경·취소는 reserved에서만.
    """
    RESERVED = "reserved"
    PREPARING = "preparing"    # 준비 — Pinky가 약제실로 오는 중, OMX가 물품을 들고 기다림 (2026-10-29)
    CANCELLED = "cancelled"
    DISPATCHED = "dispatched"
    ARRIVED = "arrived"
    RECEIVED = "received"
    FAILED = "failed"


class DeliveryFailureReason(StrEnum):
    """배송 실패 사유 (로봇이 progress로 보고, 2026-10-20)."""
    NAVIGATION_FAILED = "navigation_failed"      # 목적지까지 주행 실패 (Nav2 중단·시간 초과)
    NOT_RECEIVED = "not_received"                # 도착 후 수령 대기 시간 안에 수령 없음
    DESTINATION_BLOCKED = "destination_blocked"  # 목적지가 실행기 설정의 금지 장소
    ROBOT_ERROR = "robot_error"                  # 그 밖의 로봇 쪽 오류


class DeliveryEventType(StrEnum):
    """배송 기록(delivery_events)의 사건 종류 (2026-10-21, 로드맵 4단계).
    간호사: 예약·변경·취소. 로봇: 출발(claim)·도착·수령·실패. 상태가 실제로 바뀐 때만 남긴다(멱등 재보고·거부는 남기지 않음).
    """
    RESERVED = "reserved"      # 간호사 예약
    UPDATED = "updated"        # 간호사 변경 (바뀐 값만 details에)
    CANCELLED = "cancelled"    # 간호사 취소
    PREPARING = "preparing"    # 준비 — FMS가 Pinky를 약제실로 부름 (2026-10-29)
    DISPATCHED = "dispatched"  # 로봇이 맡아 출발 (FMS 연동: 약제실 정밀 주차 끝)
    ARRIVED = "arrived"        # 로봇 도착 보고 (일회용 마커 번호는 기록하지 않음)
    RECEIVED = "received"      # 로봇이 일회용 마커로 수령 확인
    FAILED = "failed"          # 로봇 실패 보고 (사유는 details)


class DeliveryEventActor(StrEnum):
    """배송 기록의 행위자 종류."""
    NURSE = "nurse"
    ROBOT = "robot"
    BEDSIDE = "bedside"   # 병상 단말 (환자 요청·받았습니다 버튼, 2026-10-22)


class DeliveryRequester(StrEnum):
    """배송을 만든 쪽 (2026-10-22). 병상 배송은 간호사 승인 없이 바로 생기고, 수령은 병상 화면 버튼으로."""
    NURSE = "nurse"       # 간호사 예약 — 수령은 일회용 마커
    BEDSIDE = "bedside"   # 병상 단말 환자 요청 — 수령은 "받았습니다" 버튼


class ReceiptMethod(StrEnum):
    """수령 방법. 저장하지 않고 배송마다 계산한다(Delivery.receipt_method). 설정 NURSE_RECEIPT_METHOD는 button·marker만."""
    BUTTON = "button"   # 간호사·환자가 화면에서 "받았습니다"
    MARKER = "marker"   # 로봇이 일회용 마커를 읽음 (간호사 배송, NURSE_RECEIPT_METHOD=marker)
    NONE = "none"       # 로봇 전용 장소(충전 등)로의 품목 없는 이동 — 도착 보고가 곧 완료


class RobotType(StrEnum):
    """로봇 종류. 등록 후 바꿀 수 없다."""
    MANIPULATOR = "manipulator"  # 적재 장소에서 비품을 집어 싣는 로봇팔
    AMR = "amr"                  # 병실까지 주행하는 배송 로봇


class RobotStatus(StrEnum):
    """로봇 상태. 지금은 API(PATCH /robots/{id})로만 바뀐다."""
    IDLE = "idle"                # 대기
    DELIVERING = "delivering"    # 배송 중
    CHARGING = "charging"        # 충전 중
    MAINTENANCE = "maintenance"  # 점검·사용 불가
    # [검토 필요] 상태 종류는 가정값이고 두 종류 공통이다. 매니퓰레이터에 delivering·charging이 맞지 않으므로 종류별 상태를 로봇 부서와 정해야 한다.


class FmsOrderStatus(StrEnum):
    """팀원 FMS 주문 상태 (FMS API v1 Order.status 그대로, 2026-10-27). fms_orders.status에 저장한다."""
    QUEUED = "queued"          # 노는 핑키를 기다림 — 이때만 FMS가 취소를 받는다
    ASSIGNED = "assigned"      # 묶음에 들어감 (batch_assigned)
    LOADED = "loaded"          # 핑키에 실림
    DELIVERED = "delivered"    # 병실에서 한 바퀴 끝 (order_delivered)
    CANCELED = "canceled"
    FAILED = "failed"


class FmsBatchStep(StrEnum):
    """FMS 묶음의 OMX 적재 단계 (2026-10-27, 연동 2단계 — services/fms_omx.py). PICK → PICKING → READY → CALLED → PINKY → LOADING → LOADED → DELIVERING."""
    PICK = "pick"              # /command {"blue": N, "green": N}를 보낼 차례 (OMX가 비면)
    PICKING = "picking"        # OMX가 집는 중 — /status로 끝났는지 본다
    READY = "ready"            # OMX가 집어서 들었다 → FMS ready를 보낼 차례
    CALLED = "called"          # Pinky가 약제실로 오는 중 (robot_at_pharmacy = 정밀 주차 끝을 기다림)
    PINKY = "pinky"            # 정밀 주차 끝 → /pinky(내려놓기)를 보낼 차례
    LOADING = "loading"        # OMX가 Pinky 위에 내려놓고 시작 자세로 돌아가는 중 — /status로 끝났는지 본다
    LOADED = "loaded"          # 다 실었다 → FMS loaded를 보낼 차례
    DELIVERING = "delivering"  # FMS에 loaded를 보냄 (끝)
    FAILED = "failed"          # OMX 실패·거절 (error에 까닭, 사람이 봐야 함)


class NotificationEvent(StrEnum):
    """실시간 알림(SSE) 종류 (2026-10-16). 알림은 저장하지 않는다 — 지금 부족한 비품 목록은 재고에서 바로 계산한다.
    재고 알림은 모든 간호사에게. 배송 단계 알림은 예약한 간호사 본인에게(payload의 recipient_nurse_id — 2026-10-19),
    실패는 관리자에게도(recipient_role — 2026-10-20). 받는 사람 거르기는 app/core/notification_hub.py
    """
    LOW_STOCK = "low_stock"                    # 재고가 기준 수량 이하로 내려감
    LOW_STOCK_RESOLVED = "low_stock_resolved"  # 다시 기준 수량 위로 (입고·취소·기준 변경·삭제)
    DELIVERY_DISPATCHED = "delivery_dispatched"  # 로봇이 배송을 맡아 출발 (2026-10-20)
    DELIVERY_ARRIVED = "delivery_arrived"        # 목적지 도착 — 일회용 수령 마커 포함, 예약 간호사에게만 (2026-10-20)
    DELIVERY_RECEIVED = "delivery_received"      # 로봇이 일회용 마커로 수령을 확인함 (2026-10-19)
    DELIVERY_FAILED = "delivery_failed"          # 실패(사유) — 예약 간호사 + 관리자 (2026-10-20)


def check_values(enum_cls: type[StrEnum]) -> str:
    """Enum 값들을 SQL CHECK 제약용 IN 리스트 문자열로 만든다.
    [입력] enum_cls: StrEnum 클래스
    [출력] str: "'a', 'b', 'c'"
    """
    return ", ".join(f"'{v.value}'" for v in enum_cls)
