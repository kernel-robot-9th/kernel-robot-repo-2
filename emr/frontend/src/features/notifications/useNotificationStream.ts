// =============================================================================
// 파일   : src/features/notifications/useNotificationStream.ts
// 역할   : 실시간 알림(SSE /notifications/stream) 연결 유지 — 로그인 후 화면(Layout)에서 한 번 부른다
// 작성일 : 2026-10-16
// 구성   :
//   - useNotificationStream()  연결·재연결. 알림이 오면 비품·재고 부족 목록을 다시 불러오고, 부족해졌으면 토스트
//   - describeReceivedItems()  수령 완료 토스트의 품목 문구
// 수령 완료(delivery_received)는 서버가 예약한 간호사에게만 보낸다 — 오면 배송 목록을 다시 불러오고 초록 토스트 (2026-10-19)
// 서버는 10분마다 연결을 닫는다(토큰·계정 재검사) — 그때와 끊겼을 때 RECONNECT_DELAYS_MS 간격으로 다시 붙는다
// 401이면 다시 붙지 않고 내 정보를 다시 불러 main.tsx의 401 처리(로그인 화면으로)를 태운다
// =============================================================================
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiRequestError, streamServerSentEvents } from '../../api/client'
import { keys } from '../../api/hooks'
import type { DeliveryReceivedEvent, DeliveryStageEvent, LowStockEvent, Nurse } from '../../api/types'
import { DELIVERY_FAILURE_REASON_LABEL } from '../../api/types'
import { showToast } from './toastStore'

const RECONNECT_DELAYS_MS = [1_000, 3_000, 10_000, 30_000]   // 연속으로 실패할수록 길게. 마지막 값을 계속 쓴다

/** 수령 완료 토스트의 품목 문구. [입력] received [출력] 예: "A 약품 3개 외 1건" */
export function describeReceivedItems(received: Pick<DeliveryReceivedEvent, 'items' | 'item_count'>): string {
  const [first] = received.items
  if (!first) return `품목 ${received.item_count}건`
  const others = received.item_count - 1
  return `${first.name} ${first.quantity}개${others > 0 ? ` 외 ${others}건` : ''}`
}

/** 배송 단계 알림 토스트. 실패는 관리자에게도 오므로, 내 예약이 아니면 '관리자 알림'으로 쓴다.
 *  [입력] event / stage: SSE data / myNurseId: 로그인한 간호사 [출력] 없음 */
function showDeliveryToast(event: string, stage: DeliveryStageEvent, myNurseId: number | undefined): void {
  const what = `${stage.destination_location_name} 배송(${describeReceivedItems(stage)})`
  const robot = stage.robot_name ?? '로봇'
  if (event === 'delivery_dispatched') {
    showToast('로봇 출발', `${robot}이(가) ${what}을 가지고 출발했습니다.`, 'info')
  } else if (event === 'delivery_arrived') {
    showToast('로봇 도착', `${robot}이(가) ${stage.destination_location_name}에 도착했습니다. 화면에 뜬 수령 마커를 로봇 카메라에 보여 주세요.`, 'info')
  } else if (event === 'delivery_received') {
    showToast('배송 수령 완료', `${robot}이(가) ${what}의 수령을 확인했습니다.`, 'success')
  } else if (event === 'delivery_failed') {
    const reason = stage.failure_reason ? DELIVERY_FAILURE_REASON_LABEL[stage.failure_reason] : '로봇이 실패를 보고했습니다'
    const mine = myNurseId === undefined || myNurseId === stage.recipient_nurse_id
    showToast(mine ? '배송 실패' : '배송 실패 (관리자 알림)', `#${stage.delivery_id} ${what}: ${reason}. 재고는 되돌렸습니다.`, 'error')
  }
}

/** 실시간 알림 연결. [입력] 없음 [출력] connected: 지금 연결되어 있는지 (알림창에 표시) */
export function useNotificationStream(): { connected: boolean } {
  const qc = useQueryClient()
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    const refreshStock = () => Promise.all([
      qc.invalidateQueries({ queryKey: keys.lowStock }),
      qc.invalidateQueries({ queryKey: keys.supplies }),
    ])

    const handleEvent = (event: string, data: string) => {
      if (event.startsWith('delivery_')) {
        // 배송 단계가 바뀌었다 — 목록을 새로 불러온다. 도착 마커 창은 목록을 보고 Layout(ReceiptMarkerWatcher)이 띄운다
        void qc.invalidateQueries({ queryKey: keys.deliveries })
        if (event === 'delivery_failed') {
          // 실패는 재고를 되돌린다 — 비품·재고 부족 목록도
          void refreshStock()
        }
        try {
          showDeliveryToast(event, JSON.parse(data) as DeliveryStageEvent, qc.getQueryData<Nurse>(keys.me)?.id)
        } catch { /* 형식이 다르면 목록 갱신만 */ }
        return
      }
      if (event !== 'low_stock' && event !== 'low_stock_resolved') return
      void refreshStock()
      if (event !== 'low_stock') return
      try {
        const lowStock = JSON.parse(data) as LowStockEvent
        showToast('재고 부족', `${lowStock.name}(${lowStock.code}) 재고가 ${lowStock.stock_qty}개 남았습니다. (알림 기준 ${lowStock.low_stock_threshold_qty}개)`)
      } catch { /* 형식이 다르면 목록 갱신만 */ }
    }

    const run = async () => {
      let failureCount = 0
      while (!controller.signal.aborted) {
        try {
          await streamServerSentEvents('/notifications/stream', handleEvent, controller.signal, () => {
            setConnected(true)
            void refreshStock()   // 끊긴 동안 놓친 변화를 맞춘다
          })
          failureCount = 0       // 서버가 정상적으로 닫음 — 곧바로 다시 붙는다
        } catch (error) {
          if (error instanceof ApiRequestError && error.status === 401) {
            void qc.invalidateQueries({ queryKey: keys.me })   // 401 → main.tsx가 로그인 화면으로 보낸다
            return
          }
          failureCount += 1
        }
        if (controller.signal.aborted) return
        setConnected(false)
        const delay = RECONNECT_DELAYS_MS[Math.min(failureCount, RECONNECT_DELAYS_MS.length - 1)]
        await new Promise(resolve => window.setTimeout(resolve, failureCount === 0 ? 0 : delay))
      }
    }
    void run()
    return () => controller.abort()
  }, [qc])

  return { connected }
}
