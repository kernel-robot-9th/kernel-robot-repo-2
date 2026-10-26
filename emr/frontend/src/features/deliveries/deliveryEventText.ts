// =============================================================================
// 파일   : src/features/deliveries/deliveryEventText.ts
// 역할   : 배송 기록 한 줄을 사람이 읽는 문장으로 — 간호사 기록 창과 관리자 기록 화면이 같이 쓴다 (2026-10-21)
// 작성일 : 2026-10-21
// 구성   :
//   - describeEvent     사건별 내용 (예약 내용, 바뀐 것 전 → 후, 실패 사유). 이름은 기록 당시 값
// =============================================================================
import type {
  DeliveryEvent, DeliveryEventItem, FailedEventDetails, ReservedEventDetails, UpdatedEventDetails,
} from '../../api/types'
import { DELIVERY_FAILURE_REASON_LABEL } from '../../api/types'
import { formatDateTime } from '../../lib/dateFormat'

const formatItems = (items: DeliveryEventItem[]) =>
  items.map(item => `${item.name} ×${item.quantity}`).join(', ')

/** 사건 내용 한 줄 (없으면 빈 문자열).
 *  [입력] event / [출력] 예: "301호 · A 약품 ×2 · 예약 시각 26. 10. 21. 오후 5:00" */
export function describeEvent(event: DeliveryEvent): string {
  if (event.details == null) return ''
  switch (event.event_type) {
    case 'reserved': {
      const details = event.details as ReservedEventDetails
      return `${details.destination.name} · ${formatItems(details.items)} · 예약 시각 ${formatDateTime(details.scheduled_at)}`
    }
    case 'updated': {
      const details = event.details as UpdatedEventDetails
      const changes: string[] = []
      if (details.scheduled_at) {
        changes.push(`예약 시각 ${formatDateTime(details.scheduled_at.from)} → ${formatDateTime(details.scheduled_at.to)}`)
      }
      if (details.destination) changes.push(`목적지 ${details.destination.from.name} → ${details.destination.to.name}`)
      if (details.items) changes.push(`품목 ${formatItems(details.items.from)} → ${formatItems(details.items.to)}`)
      return changes.join(' / ')
    }
    case 'failed': {
      const details = event.details as FailedEventDetails
      return DELIVERY_FAILURE_REASON_LABEL[details.failure_reason] ?? details.failure_reason
    }
    default:
      return ''
  }
}
