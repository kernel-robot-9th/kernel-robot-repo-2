// =============================================================================
// 파일   : src/features/deliveries/receiptMarkerStore.ts
// 역할   : 수령 마커 창 열기 요청 — 배송 목록의 '수령 마커' 버튼 → Layout의 ReceiptMarkerWatcher (2026-10-20)
// 작성일 : 2026-10-20
// 구성   :
//   - openReceiptMarker()       열기 요청 / clearReceiptMarkerRequest()  요청 지우기
//   - useReceiptMarkerRequest() 지금 요청된 배송 id (모듈 상태라 React 밖에서도 부를 수 있다)
// =============================================================================
import { useSyncExternalStore } from 'react'

let requestedDeliveryId: number | null = null
const listeners = new Set<() => void>()

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
const setRequested = (deliveryId: number | null) => {
  requestedDeliveryId = deliveryId
  listeners.forEach(listener => listener())
}

/** 마커 창 열기 요청. [입력] deliveryId [출력] 없음 */
export function openReceiptMarker(deliveryId: number): void {
  setRequested(deliveryId)
}

/** 요청 지우기 (그 배송의 창을 닫을 때). [입력] deliveryId [출력] 없음 */
export function clearReceiptMarkerRequest(deliveryId: number): void {
  if (requestedDeliveryId === deliveryId) setRequested(null)
}

/** 지금 요청된 배송 id. [입력] 없음 [출력] number | null */
export function useReceiptMarkerRequest(): number | null {
  return useSyncExternalStore(subscribe, () => requestedDeliveryId)
}
