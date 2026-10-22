# EMR Supply Backend

비품 관리(SR-01) + 간호사 관리 + 로그인 뼈대. 비품·간호사·배송 API는 로그인 필요, 장소·로봇 API는 아직 토큰 없이 호출 가능.
요청·배송·로봇·환자·인증은 2026-10-14에 걷어냈고, 이 뼈대 위에 단계적으로 다시 올린다.

## 기동
```bash
docker compose up -d db
./setup.sh && source ~/venv/emr/bin/activate
cp .env.example .env                   # JWT_SECRET을 반드시 채운다 (없으면 기동 실패)
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload          # http://localhost:8000/docs  (N001 / nurse1234)
```

## API
- `POST /api/v1/auth/login` — 사번·비밀번호 → Bearer 토큰(8시간), `GET /api/v1/auth/me` — 토큰의 간호사 정보
- `GET/POST /api/v1/supplies`, `GET/PATCH/DELETE /api/v1/supplies/{id}` — 비품 검색·등록·편집·soft delete (로그인 필요)
- `GET/POST /api/v1/nurses`, `GET/PATCH/DELETE /api/v1/nurses/{id}` — 간호사 조회·등록·편집·비활성화 (로그인 필요, 자기 자신 비활성화 불가)
- `GET/POST /api/v1/maps`, `GET/PATCH/DELETE /api/v1/maps/{id}` — 맵 파일 이름·맵 정보(resolution·origin)
- `GET/POST /api/v1/locations`, `GET/PATCH/DELETE /api/v1/locations/{id}` — 장소(배송 위치·맵 좌표) 조회·등록·편집·삭제
- `GET/POST /api/v1/robots`, `GET/PATCH/DELETE /api/v1/robots/{id}` — 로봇 등록·조회·수정·삭제, 종류(manipulator·amr)·이름·상태 (`?robot_type=`, `?status=`로 필터)
- `GET/POST /api/v1/deliveries`, `GET/PATCH /api/v1/deliveries/{id}`, `POST .../{id}/cancel` — 배송 일정 예약 (로그인 필요, 본인 예약만)
- `GET/POST /api/v1/bedside-devices`, `PATCH/DELETE …/{id}`, `POST/DELETE …/{id}/api-key` — 병상 단말 등록·병실·키 (관리자, 2026-10-22)
- `GET /api/v1/bedside/me`·`/supplies`·`/deliveries`, `POST /bedside/requests`, `POST /bedside/deliveries/{id}/receipt` — 병상 단말(`X-Bedside-Api-Key`): 환자 비품 요청·"받았습니다"
- `GET /api/v1/deliveries/{id}/events` — 배송 한 건의 기록(예약·변경·취소·출발·도착·수령·실패, 본인·관리자), `GET /api/v1/delivery-events` — 관리자 배송 기록(거르기·최근 순) (2026-10-21)

## 테스트
```bash
pytest                                                                          # 단위
TEST_DATABASE_URL=postgresql+psycopg://emr:emr@localhost:5432/emr_test pytest   # 통합 포함
```

## 구조
`api → services → repositories → models`.

## 주석 규약
- 파일 헤더: 역할·작성일·구성 목록
- 클래스 docstring 3줄 이내, 메서드 1줄 + `[입력]` `[출력]`
- 결정이 필요한 지점은 `# [검토 필요] 사유` — `python -m scripts.review` 로 `REVIEW.md` 재생성
- `/docs`(OpenAPI)는 라우터 `summary/description/responses` + 스키마 `Field(description=)`로 별도 관리
