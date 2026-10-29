// =============================================================================
// 파일   : src/features/deliveries/DeliveryProgress.tsx
// 역할   : 배송 단계 표시 — 예약 → 준비(2026-10-29) → 출발 → 도착 → 수령, 실패·취소는 사유와 함께 (로드맵 2단계, 2026-10-20)
// 작성일 : 2026-10-20
// 구성   :
//   - (useNowMs는 useNowMs.ts로 옮김, 2026-10-22)
//   - DeliveryProgress  한 줄 단계 표시 + 지금 단계의 시각·로봇 이름
// =============================================================================
import type { Delivery } from '../../api/types'
import { DELIVERY_FAILURE_REASON_LABEL } from '../../api/types'
import { formatHourMinute } from '../../lib/dateFormat'
import { useNowMs } from './useNowMs'

const STEPS = [
  { status: 'reserved', label: '신청' },
  { status: 'preparing', label: '준비' },   // FMS가 Pinky를 약제실로 부름 → 정밀 주차 끝이 출발 (2026-10-29)
  { status: 'dispatched', label: '출발' },
  { status: 'arrived', label: '도착' },
  { status: 'received', label: '받음' },
] as const


/** 지금 단계의 순번 (실패는 어디서 멈췄는지로). [입력] delivery [출력] 0~4 */
function stepIndex(delivery: Delivery): number {
  if (delivery.status === 'failed') return delivery.arrived_at ? 3 : delivery.dispatched_at ? 2 : 1
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
  // 로봇은 로봇 목적지 이름(robot_dest)이 있는 장소의 배송만 가져간다 (2026-10-27, 전에는 좌표·복귀 장소 맵)
  const robotCanGo = delivery.destination_location?.robot_dest != null

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
        {delivery.status === 'reserved' && !robotCanGo && <span className="text-amber-700">운반 로봇이 갈 수 없는 장소라 출발하지 않습니다. 관리자에게 문의해 주세요.</span>}
        {delivery.status === 'reserved' && robotCanGo && (overdue ? '곧 운반 로봇이 출발합니다.' : '보낼 시간이 되면 운반 로봇이 출발합니다.')}
        {delivery.status === 'preparing' && '약제실에서 물품을 준비하고 있습니다.'}
        {delivery.status === 'dispatched' && `운반 로봇이 ${formatHourMinute(delivery.dispatched_at)}에 출발했습니다.`}
        {delivery.status === 'arrived' && '병동에 도착했습니다. 받아 주세요.'}
        {delivery.status === 'received' && `${formatHourMinute(delivery.received_at)} 받음`}
        {failed && <span className="text-red-700">{delivery.failure_reason ? DELIVERY_FAILURE_REASON_LABEL[delivery.failure_reason] : '배송하지 못했습니다.'}</span>}
      </p>
    </div>
  )
}
