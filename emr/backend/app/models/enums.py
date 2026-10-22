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
    reserved → cancelled(간호사 취소) / dispatched·arrived → failed(로봇 실패 보고, 재고 복구)
    간호사 변경·취소는 reserved에서만.
    """
    RESERVED = "reserved"
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
    DISPATCHED = "dispatched"  # 로봇이 맡아 출발
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
