# =============================================================================
# 파일   : app/schemas/common.py
# 역할   : 모든 *Out 스키마의 베이스 (from_attributes)
# 작성일 : 2026-10-13
# 구성   :
#   - OrmOut  
# =============================================================================
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class OrmOut(BaseModel):
    """ORM 객체 → 응답 변환용 베이스. 모든 *Out 스키마가 상속한다.
    from_attributes=True 덕에 `XOut.model_validate(orm_obj)` 한 줄로 변환되며,
    필드를 명시적으로 나열하므로 모델에 컬럼이 추가돼도 자동으로 새나가지 않는다.
    """

    model_config = ConfigDict(from_attributes=True)
