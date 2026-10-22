// =============================================================================
// 파일   : src/features/deliveries/DeliveryProgress.tsx
// 역할   : 배송 단계 표시 — 예약 → 출발 → 도착 → 수령, 실패·취소는 사유와 함께 (로드맵 2단계, 2026-10-20)
// 작성일 : 2026-10-20
// 구성   :
//   - (useNowMs는 useNowMs.ts로 옮김, 2026-10-22)
//   - DeliveryProgress  한 줄 단계 표시 + 지금 단계의 시각·로봇 이름
// =============================================================================
import type { Delivery } from '../../api/types'
import { DELIVERY_FAILURE_REASON_LABEL } from '../../api/types'
import { useNowMs } from './useNowMs'

const STEPS = [
  { status: 'reserved', label: '예약' },
  { status: 'dispatched', label: '출발' },
  { status: 'arrived', label: '도착' },
  { status: 'received', label: '수령' },
] as const

const time = (iso: string | null) => iso ? new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : ''

/** 지금 단계의 순번 (실패는 어디서 멈췄는지로). [입력] delivery [출력] 0~3 */
function stepIndex(delivery: Delivery): number {
  if (delivery.status === 'failed') return delivery.arrived_at ? 2 : 1
  return Math.max(0, STEPS.findIndex(step => step.status === delivery.status))
}

/** [입력] delivery: destination_location의 맵 좌표가 없으면 로봇이 맡지 않는다는 안내를 붙인다 */
export function DeliveryProgress({ delivery }: { delivery: Delivery }) {
  const nowMs = useNowMs()
  if (delivery.status === 'cancelled') {
    return <span className="text-sm text-slate-500">취소됨</span>
  }
  const current = stepIndex(delivery)
  const failed = delivery.status === 'failed'
  const overdue = delivery.status === 'reserved' && new Date(delivery.scheduled_at).getTime() <= nowMs
  const hasCoordinates = delivery.destination_location?.map_x_m != null

  return (
    <div className="space-y-1">
      <ol className="flex items-center gap-1 text-xs" aria-label="배송 단계">
        {STEPS.map((step, index) => {
          const done = index < current || (index === current && delivery.status === 'received')
          const here = index === current && !done
          const tone = failed && here ? 'bg-red-600 text-white'
            : here ? 'bg-teal-600 text-white'
            : done ? 'bg-teal-100 text-teal-800'
            : 'bg-slate-100 text-slate-400'
          return (
            <li key={step.status} className="flex items-center gap-1" aria-current={here ? 'step' : undefined}>
              {index > 0 && <span aria-hidden className={`h-px w-3 ${index <= current ? 'bg-teal-400' : 'bg-slate-200'}`} />}
              <span className={`rounded px-1.5 py-0.5 font-medium ${tone}`}>{failed && here ? '실패' : step.label}</span>
            </li>
          )
        })}
      </ol>
      <p className="text-xs text-slate-500">
        {delivery.status === 'reserved' && !hasCoordinates && <span className="text-amber-700">목적지 좌표가 없어 로봇이 맡지 않습니다 (관리자에게 장소 좌표 등록 요청)</span>}
        {delivery.status === 'reserved' && hasCoordinates && (overdue ? '로봇 배정을 기다리는 중' : '예약 시각이 되면 로봇이 출발합니다')}
        {delivery.status === 'dispatched' && `${delivery.assigned_robot_name ?? '로봇'} 출발 ${time(delivery.dispatched_at)}`}
        {delivery.status === 'arrived' && `${delivery.assigned_robot_name ?? '로봇'} 도착 ${time(delivery.arrived_at)} · 수령 마감 ${time(delivery.receipt_deadline_at)}`}
        {delivery.status === 'received' && `수령 ${time(delivery.received_at)}`}
        {failed && <span className="text-red-700">{delivery.failure_reason ? DELIVERY_FAILURE_REASON_LABEL[delivery.failure_reason] : '실패'} · 재고는 되돌렸습니다</span>}
      </p>
    </div>
  )
}
