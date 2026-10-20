# =============================================================================
# 파일   : pinky_marker/follow_logic.py
# 역할   : 간호사 따라가기 제어식·상태 판단 (ROS를 모른다 — 단위 테스트 대상). 팀원 marker_follower_2.py에서 옮기고
#          Nav2와 부딪히지 않게 상태 NAV_BUSY·DISABLED를 더함 (2026-10-20)
# 작성일 : 2026-10-20
# 구성   :
#   - FollowParams     제어 파라미터 (단위는 이름에)
#   - compute_command()  마커 중심·크기 → (선속도 m/s, 각속도 rad/s, 거리 m, 좌우 오차)
#   - decide_state()   마지막으로 본 시각·Nav2 주행 여부·켜짐 → 상태
#   - publishes_velocity()  그 상태에서 /cmd_vel을 낼지 — FOLLOWING일 때만(그 밖엔 멈출 때 정지 몇 번만)
# 상태: DISABLED(꺼짐) · NAV_BUSY(Nav2 주행 중 — 비켜 있음) · WAITING · FOLLOWING · SHORT_LOSS(멈춤, 다시 찾는 중) · TARGET_LOST(멈춤 + 알림)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

DISABLED = 'DISABLED'
NAV_BUSY = 'NAV_BUSY'
WAITING = 'WAITING'
FOLLOWING = 'FOLLOWING'
SHORT_LOSS = 'SHORT_LOSS'
TARGET_LOST = 'TARGET_LOST'


@dataclass
class FollowParams:
    marker_size_m: float = 0.05        # 검정 정사각형 한 변 (EMR 인쇄 카드는 50 mm)
    focal_px: float = 500.0            # 카메라 초점 거리(px) — 보정 전 가정값
    follow_distance_m: float = 0.30
    linear_gain: float = 0.6
    angular_gain: float = 0.8
    max_linear_mps: float = 0.10
    max_backward_mps: float = 0.05
    max_angular_radps: float = 0.5
    distance_deadband_m: float = 0.03
    angular_deadband: float = 0.05     # 좌우 오차(-1~1) 이하면 돌지 않음
    stop_timeout_s: float = 0.5        # 이만큼 안 보이면 멈춤
    lost_timeout_s: float = 3.0        # 이만큼 안 보이면 TARGET_LOST
    invert_x: bool = True              # Pinky 카메라가 180° 돌아 달림 (팀원 확인)


def compute_command(center_x_px: float, width_px: float, image_width_px: int, params: FollowParams) -> tuple[float, float, float, float]:
    """비례 제어. 가까우면 뒤로(느리게), 멀면 앞으로, 옆이면 돈다. 도는 동안 전진을 줄인다.
    [출력] (linear_mps, angular_radps, distance_m, x_error)
    """
    distance_m = params.focal_px * params.marker_size_m / max(width_px, 1e-6)
    x_error = (center_x_px - image_width_px / 2.0) / (image_width_px / 2.0)   # -1(왼쪽) .. +1(오른쪽)
    if params.invert_x:
        x_error = -x_error
    angular = 0.0 if abs(x_error) < params.angular_deadband else -params.angular_gain * x_error
    angular = max(-params.max_angular_radps, min(params.max_angular_radps, angular))
    distance_error = distance_m - params.follow_distance_m
    linear = 0.0 if abs(distance_error) < params.distance_deadband_m else params.linear_gain * distance_error
    linear *= max(0.0, 1.0 - abs(x_error))
    linear = max(-params.max_backward_mps, min(params.max_linear_mps, linear))
    return linear, angular, distance_m, x_error


def decide_state(enabled: bool, navigation_active: bool, last_seen_s: float | None, now_s: float, params: FollowParams) -> str:
    """[입력] enabled: 따라가기 켜짐 / navigation_active: Nav2 목표 수행 중 / last_seen_s: 대상 마커를 마지막으로 본 시각
    [출력] 상태 이름"""
    if not enabled:
        return DISABLED
    if navigation_active:
        return NAV_BUSY
    if last_seen_s is None:
        return WAITING
    age_s = now_s - last_seen_s
    if age_s < params.stop_timeout_s:
        return FOLLOWING
    if age_s < params.lost_timeout_s:
        return SHORT_LOSS
    return TARGET_LOST


def publishes_velocity(state: str) -> bool:
    """FOLLOWING일 때만 /cmd_vel을 계속 낸다 — 그 밖엔 Nav2·teleop의 명령을 덮어쓰지 않게 조용히 있는다."""
    return state == FOLLOWING


def is_valid_target(marker_id: int) -> bool:
    """따라갈 수 있는 번호는 간호사 신분증 마커(0~49)뿐 — 일회용 수령 마커(50~249)는 따라가지 않는다."""
    return 0 <= marker_id <= 49


__all__ = ['FollowParams', 'compute_command', 'decide_state', 'publishes_velocity', 'is_valid_target',
           'DISABLED', 'NAV_BUSY', 'WAITING', 'FOLLOWING', 'SHORT_LOSS', 'TARGET_LOST']
