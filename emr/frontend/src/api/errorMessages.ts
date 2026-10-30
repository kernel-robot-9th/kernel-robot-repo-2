// =============================================================================
// 파일   : src/api/errorMessages.ts
// 역할   : API 오류 → 간호사가 읽을 한국어 안내 (무슨 일인지 + 어떻게 하면 되는지)
// 작성일 : 2026-10-15
// 구성   :
//   - ERROR_GUIDES      오류 code → 안내. 백엔드에 code를 추가하면(raise ...(code="...")) 여기도 추가한다
//   - STATUS_GUIDES     code가 표에 없을 때 HTTP 상태별 기본 안내
//   - describeError()   오류 → { message, hint, technical }
// =============================================================================
import { ApiRequestError } from './client'

export interface ErrorDescription {
  message: string     // 무슨 일이 있었는지
  hint?: string       // 어떻게 하면 되는지
  technical: string   // 관리자 전달용 — 상태·코드·서버 메시지(영어)
}

type ErrorGuide = Omit<ErrorDescription, 'technical'>

const ALREADY_GONE_HINT = '다른 사람이 이미 삭제했을 수 있습니다. 화면을 새로 불러와 확인해 주세요.'
const REPORT_HINT = '계속되면 아래 기술 정보를 관리자에게 전달해 주세요.'

const ERROR_GUIDES: Record<string, ErrorGuide> = {
  // 화면에서 만드는 code (client.ts)
  network_error: { message: '서버에 연결할 수 없습니다.', hint: `네트워크 연결과 서버가 켜져 있는지 확인한 뒤 다시 시도해 주세요. ${REPORT_HINT}` },
  validation_error: { message: '입력한 값의 형식이 올바르지 않습니다.', hint: '빈 칸, 숫자 범위, 날짜 형식을 확인해 주세요.' },
  // 로그인
  invalid_credentials: { message: '사번 또는 비밀번호가 틀렸습니다.', hint: '비활성화된 계정도 로그인할 수 없습니다.' },
  token_missing: { message: '로그인이 필요합니다.', hint: '다시 로그인해 주세요.' },
  token_invalid: { message: '로그인이 만료되었습니다.', hint: '다시 로그인해 주세요.' },
  user_inactive: { message: '비활성화된 계정입니다.', hint: '관리자에게 계정 복구를 요청해 주세요.' },
  current_password_mismatch: { message: '현재 비밀번호가 틀렸습니다.', hint: '지금 쓰는 비밀번호를 다시 확인해 주세요. 잊었다면 관리자에게 초기화를 요청해 주세요.' },
  // 권한
  admin_required: { message: '관리자만 할 수 있는 작업입니다.', hint: '간호사 관리와 환경 설정(장소·맵·로봇) 변경은 관리자에게 요청해 주세요.' },
  self_role_change: { message: '자기 자신의 관리자 권한은 해제할 수 없습니다.', hint: '다른 관리자에게 요청해 주세요.' },
  // 비품
  supply_not_found: { message: '선택한 비품을 찾을 수 없습니다.', hint: ALREADY_GONE_HINT },
  supply_code_duplicate: { message: '같은 코드의 비품이 이미 있습니다.', hint: '다른 코드를 입력해 주세요. 삭제한 비품의 코드도 다시 쓸 수 없습니다.' },
  supply_field_required: { message: '이름·재고·요청 가능 대상은 비워 둘 수 없습니다.', hint: '값을 입력한 뒤 다시 저장해 주세요.' },
  // 간호사
  nurse_not_found: { message: '선택한 간호사를 찾을 수 없습니다.', hint: ALREADY_GONE_HINT },
  employee_no_duplicate: { message: '같은 사번의 간호사가 이미 있습니다.', hint: '비활성화된 간호사의 사번도 다시 쓸 수 없습니다. 목록에서 해당 간호사를 복구해 주세요.' },
  self_deactivation: { message: '자기 자신은 비활성화할 수 없습니다.', hint: '다른 관리자에게 요청해 주세요.' },
  aruco_marker_duplicate: {
    message: '이 인식표 번호는 다른 간호사가 이미 쓰고 있습니다.',
    hint: '목록에서 비어 있는 번호(0~49)를 골라 주세요. 사용 중지된 간호사의 번호를 쓰려면 그 간호사의 인식표를 먼저 빼 주세요.',
  },
  // 맵
  map_not_found: { message: '선택한 맵을 찾을 수 없습니다.', hint: ALREADY_GONE_HINT },
  map_in_use: { message: '이 맵을 쓰는 장소가 있어 삭제할 수 없습니다.', hint: '해당 장소들의 맵을 바꾸거나 장소를 먼저 삭제해 주세요.' },
  map_name_duplicate: { message: '같은 이름의 맵이 이미 있습니다.', hint: '다른 이름을 입력해 주세요.' },
  map_file_name_duplicate: { message: '같은 파일 이름의 맵이 이미 있습니다.', hint: '맵 파일 이름을 확인해 주세요.' },
  map_yaml_invalid: { message: '맵 yaml 파일을 읽을 수 없습니다.', hint: 'map_server 형식(resolution, origin: [x, y, yaw])의 yaml인지 확인해 주세요. Pinky는 map_saver_cli가 만든 .yaml을 그대로 올리면 됩니다.' },
  map_image_invalid: { message: '맵 이미지를 읽을 수 없습니다.', hint: 'yaml과 함께 만들어진 .pgm 또는 .png 파일을 올려 주세요.' },
  map_file_too_large: { message: '맵 파일이 너무 큽니다.', hint: '파일 하나 10MB, 이미지 한 변 4000픽셀까지 올릴 수 있습니다.' },
  map_name_invalid: { message: '맵 이름을 입력해 주세요.', hint: '1~64자로 입력해 주세요.' },
  map_file_name_invalid: { message: '파일 이름이 비었거나 너무 깁니다.', hint: '128자 이하 이름의 파일을 올려 주세요.' },
  map_image_not_found: { message: '이 맵에는 이미지가 없습니다.', hint: '환경 설정 화면의 맵 탭에서 맵 파일을 올려 주세요.' },
  map_id_required: { message: '좌표를 입력하려면 맵을 선택해야 합니다.', hint: '맵을 고른 뒤 다시 저장해 주세요.' },
  // 장소
  location_not_found: { message: '선택한 장소를 찾을 수 없습니다.', hint: ALREADY_GONE_HINT },
  location_name_duplicate: { message: '같은 이름의 장소가 이미 있습니다.', hint: '다른 이름을 입력해 주세요.' },
  location_in_use: {
    message: '이 장소를 목적지로 쓴 물품 신청이 있어 삭제할 수 없습니다.',
    hint: '취소된 신청도 기록으로 남기 때문에, 한 번이라도 신청에 쓰인 장소는 삭제할 수 없습니다.',
  },
  // 로봇
  robot_not_found: { message: '선택한 로봇을 찾을 수 없습니다.', hint: ALREADY_GONE_HINT },
  robot_name_duplicate: { message: '같은 이름의 로봇이 이미 있습니다.', hint: '다른 이름을 입력해 주세요.' },
  robot_has_active_delivery: { message: '배송을 진행 중인 로봇은 삭제할 수 없습니다.', hint: '배송이 수령되거나 실패로 끝난 뒤 다시 시도해 주세요.' },
  // 병상 단말·환자 요청 (2026-10-22)
  location_is_bedside_room: { message: '병상 단말의 병실로 쓰는 장소는 삭제할 수 없습니다.', hint: '병상 단말 탭에서 병실을 바꾸거나 단말을 삭제한 뒤 다시 시도해 주세요.' },
  bedside_device_not_found: { message: '병상 단말을 찾을 수 없습니다.', hint: '목록을 새로 고친 뒤 다시 시도해 주세요.' },
  bedside_name_duplicate: { message: '같은 이름의 병상 단말이 이미 있습니다.', hint: '다른 이름(예: 301호-2)을 써 주세요.' },
  bedside_has_active_delivery: { message: '진행 중인 배송이 있는 병상 단말은 삭제할 수 없습니다.', hint: '배송이 받음이나 실패로 끝난 뒤 다시 시도해 주세요.' },
  bedside_key_missing: { message: '병상 단말 키가 없습니다.', hint: '관리자에게 받은 단말 키를 입력해 주세요.' },
  bedside_key_invalid: { message: '병상 단말 키가 틀렸거나 폐기되었습니다.', hint: '관리자에게 새 키를 받아 다시 입력해 주세요.' },
  bedside_request_in_progress: { message: '이미 진행 중인 요청이 있습니다.', hint: '지금 요청이 도착해 받으신 뒤에 새로 요청해 주세요.' },
  bedside_room_has_no_position: { message: '이 병실에는 로봇이 갈 위치가 아직 없습니다.', hint: '간호사에게 알려 주세요. 관리자가 맵에서 병실 위치를 정해야 합니다.' },
  supply_not_patient_requestable: { message: '환자가 요청할 수 없는 품목입니다.', hint: '필요하면 간호사에게 말씀해 주세요.' },
  delivery_not_for_bedside: { message: '이 병상의 배송이 아닙니다.', hint: '화면을 새로 고친 뒤 다시 시도해 주세요.' },
  delivery_receipt_by_button: { message: '환자 요청 배송은 병상 화면의 "받았습니다" 버튼으로만 받을 수 있습니다.', hint: '로봇의 마커 읽기로는 수령 처리되지 않습니다.' },
  // 로봇 전용 API (배송 가져가기·진행 보고·수령 확인) — 관제 PC 배송 실행기가 받는 오류. 화면에서는 보일 일이 거의 없다
  robot_key_missing: { message: '로봇 API 키가 없습니다.', hint: '요청 헤더 X-Robot-Api-Key에 관리자가 발급한 키를 넣어 주세요.' },
  robot_key_invalid: { message: '로봇 API 키가 틀렸거나 폐기되었습니다.', hint: '환경 설정 화면의 로봇 탭에서 키를 다시 발급해 로봇에 설정해 주세요.' },
  robot_not_amr: { message: '배송은 주행 로봇(AMR)만 맡을 수 있습니다.', hint: '매니퓰레이터의 키로 배송을 가져가려 했습니다.' },
  // OMX(로봇팔) — 관리자 명령·상태 (2026-10-26)
  omx_unavailable: { message: '로봇팔(OMX) 서버가 응답하지 않습니다.', hint: 'OMX PC와 OMX API(8000번 포트)가 켜져 있는지 확인해 주세요.' },
  omx_rejected: { message: '로봇팔(OMX)이 명령을 받지 않았습니다.', hint: '다른 작업을 하고 있을 수 있습니다. OMX 상태를 확인한 뒤 다시 보내 주세요.' },
  // 음성 배송 예약 초안 (2026-10-26)
  voice_disabled: { message: '음성 신청 기능이 꺼져 있습니다.', hint: '목적지·품목을 직접 골라 신청해 주세요. 켜려면 관리자가 서버 설정(VOICE_PARSER·GEMINI_API_KEY)을 바꿔야 합니다.' },
  voice_unavailable: { message: '음성을 알아듣지 못했습니다(음성 분석 서버 응답 없음).', hint: `잠시 뒤 다시 말해 보거나, 목적지·품목을 직접 골라 주세요. ${REPORT_HINT}` },
  voice_audio_invalid: { message: '녹음 파일을 쓸 수 없습니다.', hint: '녹음이 비었거나 너무 깁니다. 30초 안으로 다시 말해 주세요.' },
  delivery_not_assigned_to_robot: { message: '이 로봇이 맡은 배송이 아닙니다.', hint: '로봇 설정의 키가 맞는지 확인해 주세요.' },
  delivery_invalid_transition: { message: '지금 배송 단계에서는 할 수 없는 보고입니다.', hint: '배송 목록에서 현재 단계를 확인해 주세요.' },
  delivery_already_received: { message: '이미 수령된 배송입니다.' },
  delivery_not_arrived: { message: '로봇이 아직 도착하지 않았거나 이미 끝난 배송입니다.', hint: '도착한 배송만 수령 확인할 수 있습니다.' },
  location_robot_dest_duplicate: { message: '이 로봇 목적지는 이미 다른 장소에 연결돼 있습니다.', hint: '로봇 목적지 이름은 장소 하나에만 붙일 수 있습니다.' },
  robot_no_active_delivery: { message: '로봇이 맡고 있는 배송이 없습니다.', hint: '배송을 가져간(claim) 뒤에 도착을 알려 주세요.' },
  delivery_receipt_by_marker: { message: '이 배송은 마커로 수령합니다.', hint: '도착 창의 마커를 로봇 카메라에 보여 주세요.' },
  receipt_marker_not_for_delivery: { message: '이 배송의 수령 마커가 아닙니다.', hint: '도착 알림에 뜬 마커를 로봇 카메라에 보여 주세요. 신분증 마커로는 받을 수 없습니다.' },
  receipt_marker_exhausted: { message: '수령 마커를 더 만들 수 없습니다.', hint: `도착해 기다리는 배송이 너무 많습니다. ${REPORT_HINT}` },
  // 배송 예약
  delivery_not_found: { message: '선택한 물품 신청을 찾을 수 없습니다.', hint: ALREADY_GONE_HINT },
  delivery_not_owned: { message: '다른 간호사의 신청은 변경하거나 취소할 수 없습니다.', hint: '본인이 등록한 신청만 바꿀 수 있습니다.' },
  delivery_not_reserved: { message: '로봇이 이미 준비·출발했거나 끝난 신청이라 변경하거나 취소할 수 없습니다.', hint: '목록을 새로 불러왔습니다. 현재 상태를 확인해 주세요.' },
  omx_sentence_disabled: { message: '로봇팔 명령은 색깔별 개수로 보내 주세요.', hint: '문장 명령은 임시 설정(OMX_COMMAND_FORMAT=sentence)을 켰을 때만 받습니다.' },
  delivery_sent_to_fms: { message: '운반 로봇 쪽에 이미 전달된 신청이라 변경하거나 취소할 수 없습니다.', hint: '꼭 바꿔야 하면 관리자에게 문의해 주세요.' },
  scheduled_at_not_future: { message: '보낼 시간이 이미 지났습니다.', hint: '지금보다 뒤의 시각을 골라 다시 저장해 주세요.' },
  delivery_destination_duplicate: { message: '같은 병동이 두 번 들어 있습니다.', hint: '한 병동으로 합쳐 주세요.' },
  delivery_item_duplicate: { message: '같은 비품이 품목에 두 번 들어 있습니다.', hint: '한 줄로 합치고 수량을 조정해 주세요.' },
  stock_insufficient: { message: '재고가 부족해서 신청할 수 없습니다.', hint: '품목 선택 칸에 보이는 재고를 확인하고 수량을 줄여 주세요. 아무것도 바뀌지 않았습니다.' },
}

const STATUS_GUIDES: Record<number, ErrorGuide> = {
  400: { message: '요청을 처리할 수 없습니다.', hint: '입력한 값을 확인해 주세요.' },
  401: { message: '로그인이 필요합니다.', hint: '다시 로그인해 주세요.' },
  403: { message: '이 작업을 할 권한이 없습니다.' },
  404: { message: '대상을 찾을 수 없습니다.', hint: ALREADY_GONE_HINT },
  409: { message: '다른 데이터와 충돌해 처리할 수 없습니다.', hint: '화면을 새로 불러와 확인해 주세요.' },
}
const SERVER_ERROR_GUIDE: ErrorGuide = { message: '서버에서 오류가 발생했습니다.', hint: `잠시 후 다시 시도해 주세요. ${REPORT_HINT}` }
const UNKNOWN_ERROR_GUIDE: ErrorGuide = { message: '알 수 없는 오류가 발생했습니다.', hint: `화면을 새로고침한 뒤 다시 시도해 주세요. ${REPORT_HINT}` }

/** 오류를 한국어 안내로 바꾼다. code 표 → HTTP 상태 → 기본 안내 순으로 찾는다.
 *  [입력] error: ApiRequestError 또는 그 밖의 예외
 *  [출력] ErrorDescription
 */
export function describeError(error: unknown): ErrorDescription {
  if (!(error instanceof ApiRequestError)) {
    return { ...UNKNOWN_ERROR_GUIDE, technical: error instanceof Error ? `${error.name}: ${error.message}` : String(error) }
  }
  const guide = ERROR_GUIDES[error.code] ?? STATUS_GUIDES[error.status]
    ?? (error.status >= 500 ? SERVER_ERROR_GUIDE : UNKNOWN_ERROR_GUIDE)
  const statusLabel = error.status === 0 ? '연결 실패' : `HTTP ${error.status}`
  return { ...guide, technical: `${statusLabel} · ${error.code} · ${error.message}` }
}
