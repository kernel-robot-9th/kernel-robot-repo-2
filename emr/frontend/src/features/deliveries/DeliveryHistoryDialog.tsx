// =============================================================================
// 파일   : src/features/deliveries/DeliveryHistoryDialog.tsx
// 역할   : 배송 한 건의 기록 창 — 예약·변경·취소·출발·도착·수령·실패를 일어난 순서로 (본인 배송, 2026-10-21)
// 작성일 : 2026-10-21
// 구성   :
//   - DeliveryHistoryDialog  네이티브 <dialog>. 열려 있는 동안 배송 목록이 새로 고쳐지면 기록도 함께 새로 고쳐진다
// =============================================================================
import { useEffect, useRef } from 'react'
import { useDeliveryEvents } from '../../api/hooks'
import { DELIVERY_EVENT_LABEL } from '../../api/types'
import { Badge, Button, LoadError } from '../../components/ui'
import { describeEvent, formatEventTime } from './deliveryEventText'

/** [입력] deliveryId / onClose */
export function DeliveryHistoryDialog({ deliveryId, onClose }: { deliveryId: number; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const events = useDeliveryEvents(deliveryId)

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  return (
    <dialog
      ref={dialogRef} onClose={onClose} aria-labelledby="delivery-history-title"
      className="m-auto w-[min(40rem,calc(100vw-2rem))] rounded-lg p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <div className="space-y-4 p-6">
        <h2 id="delivery-history-title" className="font-semibold">배송 #{deliveryId} 기록</h2>
        {events.isError ? (
          <LoadError what="배송 기록" error={events.error} onRetry={() => void events.refetch()} />
        ) : events.isPending ? (
          <p className="text-sm text-slate-500">불러오는 중…</p>
        ) : events.data.length === 0 ? (
          <p className="text-sm text-slate-500">기록이 없습니다. 배송 기록은 2026-10-21부터 남습니다 — 그 전에 만든 배송은 기록이 없습니다.</p>
        ) : (
          <ol className="space-y-2">
            {events.data.map(event => (
              <li key={event.id} className="flex gap-3 text-sm">
                <span className="w-40 shrink-0 text-slate-500">{formatEventTime(event.occurred_at)}</span>
                <span className="w-12 shrink-0"><Badge value={event.event_type} label={DELIVERY_EVENT_LABEL[event.event_type]} /></span>
                <span className="flex-1">
                  <span className="font-medium">{event.actor_name}</span>
                  <span className="text-slate-500">{event.actor_type === 'robot' ? ' (로봇)' : ''}</span>
                  {describeEvent(event) && <span className="block text-slate-600">{describeEvent(event)}</span>}
                </span>
              </li>
            ))}
          </ol>
        )}
        <div className="flex justify-end">
          <Button variant="secondary" onClick={onClose}>닫기</Button>
        </div>
      </div>
    </dialog>
  )
}
