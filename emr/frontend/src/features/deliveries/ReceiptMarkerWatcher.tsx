// =============================================================================
// 파일   : src/features/deliveries/ReceiptMarkerWatcher.tsx
// 역할   : 도착한 내 배송의 일회용 수령 마커 창을 화면 어디서든 띄운다 — Layout에 한 번 둔다 (2026-10-20)
// 작성일 : 2026-10-20
// 구성   :
//   - ReceiptMarkerWatcher  내 배송 목록(5초마다 새로 고침, SSE 도착 알림이 오면 즉시)에서 arrived + 마커인 것을 찾아
//                           자동으로 띄운다. 닫으면 그 배송은 다시 자동으로 띄우지 않는다(버튼으로는 다시 열 수 있다).
//                           수령·실패로 arrived를 벗어나면 저절로 닫힌다
// SSE 알림은 저장되지 않으므로 창은 알림이 아니라 목록을 보고 띄운다 — 새로고침·연결 끊김에도 다시 보인다
// =============================================================================
import { useState } from 'react'
import { useDeliveries, useLocations } from '../../api/hooks'
import { ReceiptMarkerDialog } from './ReceiptMarkerDialog'
import { clearReceiptMarkerRequest, useReceiptMarkerRequest } from './receiptMarkerStore'

export function ReceiptMarkerWatcher() {
  const deliveries = useDeliveries()
  const locations = useLocations()
  const requested = useReceiptMarkerRequest()
  const [dismissed, setDismissed] = useState<ReadonlySet<number>>(() => new Set())

  const waiting = (deliveries.data ?? []).filter(delivery => delivery.status === 'arrived' && delivery.receipt_marker_id != null)
  const shown = waiting.find(delivery => delivery.id === requested)
    ?? waiting.find(delivery => !dismissed.has(delivery.id))
  if (!shown) return null

  const destinationName = (locations.data ?? []).find(location => location.id === shown.destination_location_id)?.name
    ?? shown.destination_location?.name ?? `#${shown.destination_location_id}`
  const close = () => {
    setDismissed(previous => new Set(previous).add(shown.id))
    clearReceiptMarkerRequest(shown.id)
  }
  return <ReceiptMarkerDialog key={shown.id} delivery={shown} destinationName={destinationName} onClose={close} />
}
