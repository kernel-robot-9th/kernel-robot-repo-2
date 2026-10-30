// =============================================================================
// 파일   : src/api/types.ts
// 역할   : 백엔드 응답·요청 타입 — "EMR 비품·배송 백엔드 현황" 문서의 7개 테이블 + delivery_events(2026-10-21) 기준
// 작성일 : 2026-10-14
// 구성   :
//   - 공통      ApiError, Page
//   - 인증      LoginIn, TokenOut, Nurse(역할), PasswordReset, PasswordChange
//   - 마스터    Supply, Map, Location, Robot
//   - 배송      Delivery, DeliveryItem, DeliveryCreate, DeliveryUpdate, DeliveryWard·DeliveryMultiCreate(여러 병동, 2026-10-30)
//   - 배송 기록 DeliveryEvent, AdminDeliveryEvent, DeliveryEventFilters, DELIVERY_EVENT_LABEL (2026-10-21, 로드맵 4단계)
//   - 병상 단말 BedsideDevice, BedsideApiKey (관리자), BedsideMe·BedsideSupply·BedsideDelivery·BedsideRequest (환자 화면, 2026-10-22)
//   - 알림      NotificationEventType, LowStockEvent, DeliveryReceivedEvent (SSE /notifications/stream)
//   - 음성 초안 VoiceDraft, VoiceItem, VoiceLocation, VoiceCandidate, VoiceWarning (POST /api/v2/voice/parse·parse-text, 2026-10-26)
// =============================================================================
// [검토 필요] 손으로 옮긴 타입이다. 백엔드 기동 후 `npm run gen`으로 src/api/schema.d.ts를 만들고
//   필드명이 다르면 이 파일을 schema.d.ts 기준으로 고친다. (components['schemas'][...] 로 교체 가능)

/** 백엔드 오류 응답. main.py가 모든 도메인 예외를 이 형식으로 바꾼다. */
export interface ApiError {
  code: string
  detail: string
}

// ---------- 인증 ----------
export interface LoginIn {
  employee_no: string
  password: string
}
export interface TokenOut {
  access_token: string
  token_type: 'bearer'
}
/** admin: 간호사 관리·장소·맵·로봇 변경 가능 / nurse: 일반 (비품·배송 예약은 모두 가능) */
export type NurseRole = 'admin' | 'nurse'
export const NURSE_ROLE_LABEL: Record<NurseRole, string> = { admin: '관리자', nurse: '간호사' }   // 2026-10-27 '일반' → '간호사'

export interface Nurse {
  id: number
  employee_no: string
  name: string
  is_active: boolean
  role: NurseRole
  /** 신분증 대신 쓰는 ArUco 마커 번호 (DICT_4X4_50, 0~49, 중복 불가). null=미배정 */
  aruco_marker_id: number | null
}
/** password는 평문으로 보낸다(운영은 HTTPS로만). 서버가 bcrypt 해시로만 저장한다 */
export interface NurseCreate {
  employee_no: string
  name: string
  password: string
  role: NurseRole
  aruco_marker_id: number | null
}
/** aruco_marker_id만 null로 배정 해제. 다른 필드의 null은 서버가 무시한다 */
export type NurseUpdate = Partial<Pick<Nurse, 'name' | 'is_active' | 'role' | 'aruco_marker_id'>>
/** 관리자가 다른 간호사 비밀번호를 임시 값으로 초기화. POST /nurses/{id}/password-reset */
export interface PasswordReset {
  new_password: string
}
/** 본인 비밀번호 변경. POST /auth/password — 현재 비밀번호가 틀리면 400 current_password_mismatch */
export interface PasswordChange {
  current_password: string
  new_password: string
}

// ---------- 마스터 ----------
export type SupplyCategory = 'medication' | 'supply'
export type RequestableBy = 'nurse' | 'patient'

export interface Supply {
  id: number
  code: string
  name: string
  category: SupplyCategory
  requestable_by: RequestableBy
  stock_qty: number
  /** 재고가 이 수량 이하가 되면 알림. null=알림 안 함 */
  low_stock_threshold_qty: number | null
  expiry_date: string | null // YYYY-MM-DD
}
export type SupplyCreate = Omit<Supply, 'id'>
export type SupplyUpdate = Partial<Omit<Supply, 'id' | 'code'>>

/** ROS map_server yaml의 resolution·origin을 그대로 담는다 (파일은 로봇 부서 보관). */
export interface MapInfo {
  id: number
  name: string
  file_name: string
  resolution_m_per_pixel: number
  origin_x_m: number
  origin_y_m: number
  origin_yaw_rad: number
  /** 올린 맵 이미지가 있는지 (2026-10-19). 있으면 GET /maps/{id}/image — mapImageUrl() */
  has_image: boolean
  image_width_px: number | null
  image_height_px: number | null
  image_file_name: string | null   // 올린 이미지의 원래 이름 (예: my_map.pgm)
  updated_at: string               // 이미지 주소에 붙여 교체 후 새로 받는다
}

/** 배송 위치. 좌표 세 값은 함께 있거나 함께 없다. */
export interface Location {
  id: number
  name: string
  map_id: number | null
  map_x_m: number | null
  map_y_m: number | null
  map_yaw_rad: number | null
  robot_dest: string | null   // 로봇 목적지 이름 (팀원 Pinky API /dests, 예 PHARMACY). 실행기가 이 이름으로 주행 (2026-10-22)
  admin_note: string | null   // 관리자 메모 (예 "4인실 왼쪽") — 관리자 화면에만 보여 준다 (2026-10-30)
}

export type RobotType = 'amr' | 'manipulator'
/** 화면 이름 (2026-10-27 사용자 결정): amr = 운반 로봇(Pinky, 물품을 실어 나름) · manipulator = 탑재 로봇(OMX, 물품을 싣는 팔) */
export const ROBOT_TYPE_LABEL: Record<RobotType, string> = { amr: '운반 로봇', manipulator: '탑재 로봇' }
export type RobotStatus = 'idle' | 'delivering' | 'charging' | 'maintenance'
export interface Robot {
  id: number
  name: string
  robot_type: RobotType
  status: RobotStatus
  /** 로봇 전용 API(/robot/...)용 키가 발급되어 있는지. 키 자체는 발급 응답에서 한 번만 나온다 */
  has_api_key: boolean
  api_key_issued_at: string | null
  /** 로봇 서버(팀원 Pinky API) 주소, 예: http://192.168.129.107:8080. claim 때 EMR이 GET /status로 상태를 묻는다. null이면 배송을 맡지 않는다 (2026-10-23) */
  robot_server_url: string | null
  /** claim 때 로봇 서버에서 받은 마지막 배터리·오염도 (2026-10-23). null이면 아직 받은 적 없음 */
  status_report: RobotStatusReport | null
}
/** 로봇 서버에서 받은 상태. 배터리가 기준 미만·오염도가 기준 초과면 EMR이 새 배송을 주지 않는다 (기준은 백엔드 설정) */
export interface RobotStatusReport {
  battery_percent: number        // 0~100
  contamination_percent: number  // 0(깨끗)~100, 로봇이 잰 값
  reported_at: string
}
/** 병원 지도용 로봇 위치 — 팀원 FMS가 1초마다 보내는 마지막 값 (GET /robot-positions, 2026-10-29). 좌표는 맵 미터·라디안 */
export interface RobotPosition {
  fms_robot_number: number      // FMS 로봇 번호 (1·2·3)
  fms_robot_name: string | null // 핑키 이름 (예 pinky_6364)
  robot_id: number | null       // EMR 로봇 (대응이 없으면 null)
  robot_name: string | null
  map_x_m: number
  map_y_m: number
  map_yaw_rad: number
  online: boolean
  state: string | null          // FMS 로봇 state (idle·moving …)
  place: string | null          // 사람이 읽는 위치 (아래 복도, 101호 …)
  reported_at: string
  is_stale: boolean             // 연결 끊김 (오래 못 받음 또는 online=false)
  battery_percent: number | null        // 0~100 — FMS가 계산한 값 (실제 센서 아님, 2026-10-30)
  contamination_percent: number | null  // 0~100 — FMS가 계산한 값
}
export interface RobotPositions {
  map_id: number | null         // 위치를 그릴 맵 — 다른 맵을 보고 있으면 그리지 않는다
  robots: RobotPosition[]
}
/** POST /robots/{id}/api-key 응답 (관리자). api_key는 다시 조회할 수 없다 */
export interface RobotApiKey {
  robot_id: number
  api_key: string
  issued_at: string
}

// ---------- 병상 단말 (2026-10-22) ----------
/** 관리자: 병상 단말 (GET /bedside-devices) */
export interface BedsideDevice {
  id: number
  name: string            // 예: 301호-1
  location_id: number     // 병실 — 요청한 배송의 목적지
  has_api_key: boolean
  api_key_issued_at: string | null
  updated_at: string
}
export interface BedsideDeviceCreate {
  name: string
  location_id: number
}
export type BedsideDeviceUpdate = Partial<BedsideDeviceCreate>
/** POST /bedside-devices/{id}/api-key 응답. api_key는 다시 조회할 수 없다 */
export interface BedsideApiKey {
  bedside_device_id: number
  api_key: string
  issued_at: string
}
/** 환자 화면 (X-Bedside-Api-Key) — 마커·간호사 정보·재고 수량 없음 */
export interface BedsideDelivery {
  id: number
  status: DeliveryStatus
  created_at: string
  items: { name: string; quantity: number }[]
  assigned_robot_name: string | null
  dispatched_at: string | null
  arrived_at: string | null
  received_at: string | null
  failed_at: string | null
  failure_reason: DeliveryFailureReason | null
  receipt_deadline_at: string | null
}
export interface BedsideMe {
  id: number
  name: string
  room: { id: number; name: string; has_position: boolean }
  active_delivery: BedsideDelivery | null
}
export interface BedsideSupply {
  id: number
  name: string
  in_stock: boolean
}
export interface BedsideRequest {
  items: { supply_id: number; quantity: number }[]   // 품목당 1–5
}
export const BEDSIDE_MAX_QUANTITY = 5

// ---------- 배송 ----------
/** 예약 → 준비(FMS가 Pinky를 약제실로 부름, 2026-10-29) → 출발(약제실 정밀 주차 끝) → 도착(일회용 마커 생김) → 수령.
 *  예약만 간호사가 취소 가능, 준비·출발·도착에서 실패하면 failed(재고 복구). docs/api_contract_delivery_2026-10-20.md */
export type DeliveryStatus = 'reserved' | 'preparing' | 'cancelled' | 'dispatched' | 'arrived' | 'received' | 'failed'
export type DeliveryFailureReason = 'navigation_failed' | 'not_received' | 'destination_blocked' | 'robot_error'
/** 로봇이 맡아 진행 중인 상태 — 이때는 배송 목록을 더 자주 새로 고친다 */
export const ACTIVE_DELIVERY_STATUSES: readonly DeliveryStatus[] = ['preparing', 'dispatched', 'arrived']

export interface DeliveryItem {
  supply_id: number
  quantity: number
}
/** 배송을 만든 쪽: 간호사 예약(수령 = 일회용 마커) · 병상 단말 환자 요청(수령 = "받았습니다" 버튼, 2026-10-22) */
export type DeliveryRequester = 'nurse' | 'bedside'
export interface Delivery {
  id: number
  nurse_id: number | null              // 병상 요청이면 null
  requester_type: DeliveryRequester
  bedside_name: string | null          // 요청한 병상 (병상 요청일 때)
  destination_location_id: number
  scheduled_at: string // ISO 8601
  status: DeliveryStatus
  items: DeliveryItem[]
  created_at: string
  received_at: string | null           // 수령 확인 시각
  received_by_nurse_id: number | null  // 받은 간호사 (예약한 간호사 — 마커 또는 버튼)
  received_by_robot_id: number | null  // 가져다준 로봇. 로봇을 지웠으면 null
  destination_location: Location       // 목적지 상세 (맵 좌표 — 없으면 로봇이 맡지 않는다)
  assigned_robot_id: number | null     // 맡은 로봇 (2026-10-20)
  assigned_robot_name: string | null
  dispatched_at: string | null
  arrived_at: string | null
  failed_at: string | null
  failure_reason: DeliveryFailureReason | null
  receipt_marker_id: number | null     // 일회용 수령 마커 (DICT_4X4_250, 50~249). 도착 때 생긴다 — 본인 예약에만
  receipt_deadline_at: string | null   // 수령 마감 (arrived일 때만). 지나면 로봇이 미수령으로 실패 처리
  receipt_method: ReceiptMethod        // button = 도착하면 "받았습니다" / marker = 마커를 로봇 카메라에 (2026-10-22, 서버 설정)
}
/** 수령 방법 (2026-10-22): button = 화면의 "받았습니다" / marker = 일회용 마커를 로봇 카메라에 보여 줌 */
export type ReceiptMethod = 'button' | 'marker'
export interface DeliveryCreate {
  destination_location_id: number
  scheduled_at: string
  items: DeliveryItem[]
}
export type DeliveryUpdate = Partial<DeliveryCreate>
/** 여러 병동 신청 (2026-10-30, POST /deliveries/multi) — 병동마다 신청 1건, 모두 되거나 모두 안 됨 */
export interface DeliveryWard {
  destination_location_id: number
  items: DeliveryItem[]
}
export interface DeliveryMultiCreate {
  scheduled_at: string
  destinations: DeliveryWard[]
}

/** 한국어 라벨 — 화면 여러 곳에서 공유 */
export const DELIVERY_STATUS_LABEL: Record<DeliveryStatus, string> = {
  reserved: '신청됨',
  preparing: '준비',   // 2026-10-29
  cancelled: '취소',
  dispatched: '출발',
  arrived: '도착 · 수령 대기',
  received: '받음',   // 2026-10-27 화면 문구와 맞춤
  failed: '실패',
}
export const DELIVERY_FAILURE_REASON_LABEL: Record<DeliveryFailureReason, string> = {
  navigation_failed: '운반 로봇이 가지 못하였습니다. 다시 신청해 주세요.',   // 문구 2026-10-27 사용자 결정 — 모두 마침표로 끝난다
  not_received: '아무도 받지 않았습니다.',
  destination_blocked: '지금은 운반 로봇이 갈 수 없는 장소입니다.',
  robot_error: '운반 로봇에 문제가 생겼습니다. 비상 정지합니다.',
}
// ---------- 배송 기록 (2026-10-21, 로드맵 4단계) ----------
/** 간호사: 예약·변경·취소 / 로봇: 준비·출발·도착·수령·실패. 상태가 실제로 바뀐 때만 남는다 (거부·같은 보고 반복은 없음) */
export type DeliveryEventType = 'reserved' | 'updated' | 'cancelled' | 'preparing' | 'dispatched' | 'arrived' | 'received' | 'failed'
export interface DeliveryEventItem {
  supply_id: number
  name: string       // 당시 비품 이름
  quantity: number
}
export interface DeliveryEventPlace {
  id: number
  name: string       // 당시 장소 이름
}
export interface DeliveryEventChange<T> {
  from: T
  to: T
}
/** reserved — 예약 내용 */
export interface ReservedEventDetails {
  scheduled_at: string
  destination: DeliveryEventPlace
  items: DeliveryEventItem[]
}
/** updated — 바뀐 것만 */
export interface UpdatedEventDetails {
  scheduled_at?: DeliveryEventChange<string>
  destination?: DeliveryEventChange<DeliveryEventPlace>
  items?: DeliveryEventChange<DeliveryEventItem[]>
}
/** failed — 실패 사유 */
export interface FailedEventDetails {
  failure_reason: DeliveryFailureReason
}
export interface DeliveryEvent {
  id: number
  delivery_id: number
  event_type: DeliveryEventType
  occurred_at: string
  actor_type: 'nurse' | 'robot' | 'bedside'
  actor_name: string              // 간호사 이름, 로봇 이름 또는 병상 이름(당시 — 지워도 남음)
  actor_robot_id: number | null   // 로봇을 지웠으면 null
  details: ReservedEventDetails | UpdatedEventDetails | FailedEventDetails | null  // 일회용 마커 번호는 없다
}
/** 관리자 기록 화면 (GET /delivery-events) */
export interface AdminDeliveryEvent extends DeliveryEvent {
  destination_location_name: string  // 지금 이름
  requester_type: DeliveryRequester
  requester_name: string            // 예약한 간호사 이름 또는 병상 이름 (2026-10-22, 전 nurse_name)
}
/** 관리자 기록 화면 거르기. since는 포함, until은 미포함 (ISO, 시간대 포함) */
export interface DeliveryEventFilters {
  event_type?: DeliveryEventType
  robot_id?: number
  nurse_id?: number
  delivery_id?: number
  since?: string
  until?: string
}
export const DELIVERY_EVENT_LABEL: Record<DeliveryEventType, string> = {
  reserved: '신청',
  updated: '변경',
  cancelled: '취소',
  preparing: '준비',   // 2026-10-29
  dispatched: '출발',
  arrived: '도착',
  received: '받음',   // 2026-10-27 화면 문구와 맞춤
  failed: '실패',
}

export const ROBOT_STATUS_LABEL: Record<RobotStatus, string> = {
  idle: '대기',
  delivering: '배송 중',
  charging: '충전',
  maintenance: '정비',
}

// ---------- 알림 ----------
/** SSE event 이름. 알림은 서버에 저장되지 않는다 — 지금 부족한 목록은 GET /notifications/low-stock */
export type NotificationEventType =
  | 'low_stock' | 'low_stock_resolved'
  | 'delivery_dispatched' | 'delivery_arrived' | 'delivery_received' | 'delivery_failed'
/** SSE data. 재고가 기준 이하로 내려가면 low_stock, 다시 올라가면(입고·취소·기준 변경·삭제) low_stock_resolved */
export interface LowStockEvent {
  event: NotificationEventType
  supply_id: number
  code: string
  name: string
  stock_qty: number
  low_stock_threshold_qty: number | null
}
/** SSE data. 배송 단계 알림 공통 — 예약한 간호사에게 온다(실패는 관리자에게도) (2026-10-19·20) */
export interface DeliveryStageEvent {
  event: 'delivery_dispatched' | 'delivery_arrived' | 'delivery_received' | 'delivery_failed'
  recipient_nurse_id: number | null  // 병상(환자) 요청이면 null — 실패만 관리자에게 온다 (2026-10-22)
  recipient_role?: string            // delivery_failed: 'admin'
  bedside_name?: string | null       // 병상 요청이면 병상 이름
  delivery_id: number
  destination_location_name: string
  robot_name: string | null          // 로봇이 지워졌으면 null
  items: { name: string; quantity: number }[]   // 앞 5개까지
  item_count: number                 // 전체 품목 수
  dispatched_at?: string | null      // delivery_dispatched
  receipt_marker_id?: number | null  // delivery_arrived — 일회용 수령 마커 (예약자에게만)
  receipt_deadline_at?: string | null
  receipt_method?: ReceiptMethod     // delivery_arrived — button이면 "받았습니다" (2026-10-22)
  received_at?: string | null        // delivery_received
  failure_reason?: DeliveryFailureReason | null   // delivery_failed
}
/** 예전 이름 (수령 완료 알림) */
export type DeliveryReceivedEvent = DeliveryStageEvent

// ---------- 음성 배송 예약 초안 (2026-10-26) ----------
/** 매칭 후보 — supplies.id 또는 locations.id */
export interface VoiceCandidate {
  id: number
  name: string
}
/** 말한 품목과 EMR 비품의 매칭. supply_id가 null이면 확정 못 함 → candidates에서 고른다 */
export interface VoiceItem {
  spoken_name: string
  quantity: number
  supply_id: number | null
  supply_name: string | null
  score: number
  is_medication: boolean   // 약품이면 자동 확정하지 않는다 — 간호사가 확인 표시
  candidates: VoiceCandidate[]
}
export interface VoiceLocation {
  spoken_name: string | null
  location_id: number | null
  location_name: string | null
  score: number
  candidates: VoiceCandidate[]
}
export type VoiceWarning = 'medication_check' | 'item_unmatched' | 'location_missing' | 'location_unmatched' | 'no_items'
/** 초안 — 예약은 만들지 않는다. 화면이 이 값으로 배송 예약 폼을 채운다 */
export interface VoiceDraft {
  transcript: string
  location: VoiceLocation
  items: VoiceItem[]
  needs_review: boolean
  warnings: VoiceWarning[]
}
export const VOICE_WARNING_LABEL: Record<VoiceWarning, string> = {
  medication_check: '약품이 있습니다 — 품목·수량을 확인하고 "확인함"을 표시해 주세요',
  item_unmatched: '확정하지 못한 품목이 있습니다 — 후보에서 고르거나 직접 선택해 주세요',
  location_missing: '배송 장소를 말하지 않았습니다 — 목적지를 골라 주세요',
  location_unmatched: '배송 장소를 확정하지 못했습니다 — 후보에서 고르거나 직접 선택해 주세요',
  no_items: '품목을 알아듣지 못했습니다 — 다시 말하거나 직접 골라 주세요',
}
