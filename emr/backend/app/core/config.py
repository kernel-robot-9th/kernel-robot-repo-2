# =============================================================================
# 파일   : app/core/config.py
# 역할   : 환경변수(.env) 기반 전역 설정
# 작성일 : 2026-10-13
# 구성   :
#   - Settings  설정 클래스
#   - settings  모듈 import 시 생성되는 싱글턴
# =============================================================================
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(.env) 기반 전역 설정. 비밀값은 .env에만 두고 커밋하지 않는다."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "dev"                   # dev | staging | prod — prod면 /docs 비활성
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+psycopg://emr:emr@localhost:5432/emr"  # docker-compose 기본값과 동일

    JWT_SECRET: str                    # 기본값 없음 — .env에 없으면 기동 실패
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480      # 간호사 1교대(8h) 동안 재로그인 없음

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # 간호사 배송 수령 방법 (2026-10-22, 사용자 결정: 마커는 일단 끄고 간호사도 "받았습니다" 버튼).
    # button = 간호사 화면 "받았습니다"(POST /deliveries/{id}/receipt) · marker = 로봇이 일회용 마커를 읽음(2026-10-20 방식)
    # 마커를 되살리려면 .env에 NURSE_RECEIPT_METHOD=marker. 일회용 마커는 어느 쪽이든 도착 때 만든다(DB 규칙 그대로)
    NURSE_RECEIPT_METHOD: Literal["button", "marker"] = "button"

    # 로그인(JWT) 잠시 끄기 (2026-10-22, 사용자 요청: "아무나 접근 가능하게"). true면 토큰이 없거나 틀려도 관리자 AUTH_DISABLED_AS로 본다.
    # 같은 LAN 누구나 관리자 권한 — 시연·시험 동안만. 로봇 키(X-Robot-Api-Key)·병상 단말 키는 그대로 검사한다
    AUTH_DISABLED: bool = False
    AUTH_DISABLED_AS: str = "N001"
    # 로봇 API 키 잠시 끄기 (2026-10-22, 사용자 요청). true면 X-Robot-Api-Key가 없거나 틀려도 로봇 ROBOT_KEY_DISABLED_AS로 본다
    # (맞는 키를 보내면 그 로봇). 같은 LAN 누구나 로봇 API(claim·도착·실패 보고)를 부를 수 있다 — 시연·시험 동안만
    ROBOT_KEY_DISABLED: bool = False
    ROBOT_KEY_DISABLED_AS: int = 1

    # 배송 배정 때 로봇 상태 기준 (2026-10-23, 사용자 결정: "배터리, 오염도 넣어서 미션을 할당" — claim할 때마다 EMR이
    # 로봇 서버(robots.robot_server_url, 팀원 Pinky API)의 GET /status를 물어 검사). 벗어나면 claim이 새 배송을 주지 않는다
    # (204 + X-Claim-Skip-Reason). 이미 맡은 배송은 그대로 돌려준다. [검토 필요] 기준값은 가정값 — 팀원·로봇 부서와 맞춘다
    CLAIM_MIN_BATTERY_PERCENT: float = 30.0         # 이 값 미만이면 robot_battery_low
    CLAIM_MAX_CONTAMINATION_PERCENT: float = 70.0   # 이 값 초과면 robot_contamination_high
    ROBOT_SERVER_TIMEOUT_SECONDS: float = 2.0       # 로봇 서버가 이 안에 답하지 않으면 robot_server_unreachable

    # 팀원 OMX(로봇팔) API — 관리자가 EMR에서 명령을 보내고 상태를 본다 (2026-10-26, app/clients/omx.py).
    # /command는 예전 형식(명령 문장) — 10-26 합의한 색깔별 개수 형식은 팀원 쪽이 바뀐 뒤에
    OMX_BASE_URL: str = "http://192.168.129.86:8000"
    OMX_TIMEOUT_SECONDS: float = 3.0     # 이 안에 답하지 않으면 omx_unavailable(503)

    def db_host_for_log(self) -> str:
        """로그용 DB 주소 — 비밀번호 제거.
        [입력] 없음
        [출력] str: 'host:port/db' 부분만
        """
        return self.DATABASE_URL.split("@")[-1]


settings = Settings()  # 전역 싱글턴. 모듈 import 시점에 .env 로드
