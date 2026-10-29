# =============================================================================
# 파일   : app/api/v1/maps.py
# 역할   : 맵(파일 이름·맵 정보) 엔드포인트 (/maps)
# 작성일 : 2026-10-14
# 구성   :
#   - list/get                누구나 (로그인 없이 조회 — 2026-10-15 결정)
#   - create/update/delete    관리자만
#   - upload/replace_files    관리자만 — map_server yaml + 이미지(PGM·PNG) 업로드 (2026-10-19)
#   - get_map_image           누구나 — 맵 이미지 PNG
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status

from app.core.deps import ADMIN_RESPONSES, DB, get_current_admin
from app.schemas.map import MapCreate, MapOut, MapUpdate
from app.services.map import MapFile, MapService
from app.services.map_files import MAP_FILE_MAX_BYTES

router = APIRouter()
NOT_FOUND_RESPONSE = {404: {"description": "맵 없음"}}
CONFLICT_RESPONSE = {409: {"description": "name 또는 file_name 중복"}}
FILE_ERROR_RESPONSE = {400: {"description": "map_yaml_invalid · map_image_invalid · map_file_too_large · map_name_invalid · map_file_name_invalid"}}
MAP_YAML_DESCRIPTION = "map_server yaml (resolution, origin: [x, y, yaw]). 파일 이름이 maps.file_name이 된다"
MAP_IMAGE_DESCRIPTION = "맵 이미지 PGM·PNG (slam_toolbox map_saver_cli 결과). PNG로 바꿔 보관(흑백 맵은 흑백, 색 있는 평면도는 색 그대로)"


def to_map_file(upload: UploadFile) -> MapFile:
    """multipart 파일 → 서비스가 받는 MapFile. 한도보다 1바이트 더 읽어 크기 초과를 서비스가 판단하게 한다.
    [입력] upload  [출력] MapFile
    """
    return MapFile(file_name=upload.filename or "", content=upload.file.read(MAP_FILE_MAX_BYTES + 1))


@router.get("", response_model=list[MapOut], summary="맵 목록", description="이름 순.")
def list_maps(db: DB, limit: int = Query(100, le=500), offset: int = 0) -> list[MapOut]:
    """
    [입력] limit / offset
    [출력] list[MapOut]
    """
    return [MapOut.model_validate(map_) for map_ in MapService(db).list(limit, offset)]


@router.get("/{map_id}", response_model=MapOut, summary="맵 단건", responses=NOT_FOUND_RESPONSE)
def get_map(db: DB, map_id: int) -> MapOut:
    """
    [입력] map_id
    [출력] MapOut
    """
    return MapOut.model_validate(MapService(db).get(map_id))


@router.post(
    "", response_model=MapOut, status_code=status.HTTP_201_CREATED,
    summary="맵 등록 (관리자)", description="맵 yaml의 파일 이름과 resolution·origin을 등록한다.", responses={**ADMIN_RESPONSES, **CONFLICT_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def create_map(db: DB, data: MapCreate) -> MapOut:
    """
    [입력] data
    [출력] MapOut
    """
    return MapOut.model_validate(MapService(db).create(data))


@router.patch(
    "/{map_id}", response_model=MapOut,
    summary="맵 편집 (관리자)", description="보낸 필드만 바뀐다.", responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def update_map(db: DB, map_id: int, data: MapUpdate) -> MapOut:
    """
    [입력] map_id / data: 부분
    [출력] MapOut
    """
    return MapOut.model_validate(MapService(db).update(map_id, data))


@router.delete(
    "/{map_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="맵 삭제 (관리자)", description="행을 지운다. 장소가 쓰는 맵은 409.",
    responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE, 409: {"description": "장소가 사용 중"}},
    dependencies=[Depends(get_current_admin)],
)
def delete_map(db: DB, map_id: int) -> None:
    """
    [입력] map_id
    [출력] 없음 (204)
    """
    MapService(db).delete(map_id)


@router.post(
    "/upload", response_model=MapOut, status_code=status.HTTP_201_CREATED,
    summary="맵 파일로 등록 (관리자)",
    description="Pinky(slam_toolbox)가 만든 map_server yaml과 이미지를 올린다. resolution·origin은 yaml에서 읽는다.",
    responses={**ADMIN_RESPONSES, **CONFLICT_RESPONSE, **FILE_ERROR_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def upload_map(
    db: DB,
    name: str = Form(description="맵 이름 (UNIQUE)", examples=["3병동"]),
    map_yaml: UploadFile = File(description=MAP_YAML_DESCRIPTION),
    map_image: UploadFile = File(description=MAP_IMAGE_DESCRIPTION),
) -> MapOut:
    """
    [입력] name / map_yaml / map_image (multipart)
    [출력] MapOut
    """
    return MapOut.model_validate(MapService(db).create_from_files(name, to_map_file(map_yaml), to_map_file(map_image)))


@router.put(
    "/{map_id}/files", response_model=MapOut,
    summary="맵 파일 교체 (관리자)",
    description="맵을 다시 만들었을 때 yaml·이미지를 바꾼다. 장소 좌표는 그대로다 — 원점이 바뀌었으면 장소를 다시 찍어야 한다.",
    responses={**ADMIN_RESPONSES, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE, **FILE_ERROR_RESPONSE},
    dependencies=[Depends(get_current_admin)],
)
def replace_map_files(
    db: DB, map_id: int,
    map_yaml: UploadFile = File(description=MAP_YAML_DESCRIPTION),
    map_image: UploadFile = File(description=MAP_IMAGE_DESCRIPTION),
) -> MapOut:
    """
    [입력] map_id / map_yaml / map_image (multipart)
    [출력] MapOut
    """
    return MapOut.model_validate(MapService(db).replace_files(map_id, to_map_file(map_yaml), to_map_file(map_image)))


@router.get(
    "/{map_id}/image",
    summary="맵 이미지 (PNG)",
    description="누구나. 이미지가 없는 맵은 404 `map_image_not_found`. 주소에 `?v=<updated_at>`을 붙이면 교체 후 새로 받는다.",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "PNG (흑백 맵은 흑백, 평면도는 색)"}, 404: {"description": "맵 없음 · 이미지 없음"}},
)
def get_map_image(db: DB, map_id: int) -> Response:
    """
    [입력] map_id
    [출력] Response: image/png
    """
    return Response(
        content=MapService(db).get_image(map_id), media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )
