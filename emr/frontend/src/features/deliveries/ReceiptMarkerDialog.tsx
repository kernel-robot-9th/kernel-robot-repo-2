// =============================================================================
// 파일   : src/features/deliveries/ReceiptMarkerDialog.tsx
// 역할   : 도착 수령 대화상자 — receipt_method=button이면 "받았습니다" 버튼(2026-10-22 기본, 마커는 일단 끔),
//          marker면 일회용 마커를 로봇 카메라에 보여 준다 (2026-10-20)
// 작성일 : 2026-10-20
// 구성   :
//   - useSecondsLeft       마감까지 남은 초 (1초마다)
//   - ReceiptMarkerDialog  "받았습니다" 버튼 또는 큰 마커 + 안내 + 남은 시간. 수령·실패로 배송이 arrived를 벗어나면 부모가 닫는다
// 마커는 ArUco DICT_4X4_250의 50~249번, 이 배송이 도착해 있는 동안만 쓸 수 있다 (신분증 마커로는 받을 수 없다)
// =============================================================================
import { useEffect, useRef, useState } from 'react'
import { describeError } from '../../api/errorMessages'
import { useDeliveryMutations } from '../../api/hooks'
import type { Delivery } from '../../api/types'
import { Button } from '../../components/ui'
import { ArucoMarker } from '../markers/ArucoMarker'

/** 마감까지 남은 초. [입력] deadlineIso [출력] number | null (마감이 없으면 null, 지났으면 0) */
function useSecondsLeft(deadlineIso: string | null): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [])
  if (!deadlineIso) return null
  return Math.max(0, Math.floor((new Date(deadlineIso).getTime() - now) / 1_000))
}

/** [입력] delivery: arrived인 내 배송 (marker 방식이면 receipt_marker_id가 있어야 보인다) / destinationName / onClose */
export function ReceiptMarkerDialog({ delivery, destinationName, onClose }: {
  delivery: Delivery
  destinationName: string
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const secondsLeft = useSecondsLeft(delivery.receipt_deadline_at)
  const { confirmReceipt } = useDeliveryMutations()
  const byButton = delivery.receipt_method === 'button'

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  if (!byButton && delivery.receipt_marker_id == null) return null
  const minutes = secondsLeft == null ? null : Math.floor(secondsLeft / 60)
  const seconds = secondsLeft == null ? null : String(secondsLeft % 60).padStart(2, '0')

  return (
    <dialog
      ref={dialogRef} onClose={onClose} aria-labelledby="receipt-marker-title"
      className="m-auto w-[min(30rem,calc(100vw-2rem))] rounded-lg p-0 shadow-xl backdrop:bg-slate-900/50"
    >
      <div className="space-y-4 p-6 text-center">
        <div>
          <h2 id="receipt-marker-title" className="text-lg font-semibold">배송이 도착했습니다</h2>
          <p className="text-sm text-slate-600">
            #{delivery.id} · {destinationName}{delivery.assigned_robot_name ? ` · ${delivery.assigned_robot_name}` : ''}
          </p>
        </div>
        {byButton ? (
          <>
            <p className="text-sm text-slate-700">로봇에서 물건을 받은 뒤 아래 버튼을 눌러 주세요. 누르면 로봇이 돌아갑니다.</p>
            <button type="button" disabled={confirmReceipt.isPending} onClick={() => confirmReceipt.mutate(delivery.id)}
              className="w-full rounded-lg bg-green-600 py-4 text-xl font-bold text-white shadow hover:bg-green-700 disabled:opacity-50">
              받았습니다
            </button>
            {confirmReceipt.error && <p role="alert" className="text-sm text-red-700">{describeError(confirmReceipt.error).message}</p>}
          </>
        ) : (
          <>
            <div className="mx-auto w-[min(18rem,70vw)] rounded border border-slate-200 bg-white p-2">
              <ArucoMarker arucoMarkerId={delivery.receipt_marker_id!} className="h-auto w-full" />
            </div>
            <p className="text-sm text-slate-700">
              이 화면을 <b>로봇 카메라 앞</b>에 보여 주세요. 로봇이 마커를 읽으면 수령이 끝납니다.
              <br /><span className="text-xs text-slate-500">화면 밝기를 높이고, 반사가 없게 정면으로 들어 주세요. 마커 {delivery.receipt_marker_id}번 (이번 배송에만 쓰임)</span>
            </p>
          </>
        )}
        {secondsLeft != null && (
          <p className={`text-sm font-medium tabular-nums ${secondsLeft <= 60 ? 'text-red-700' : 'text-slate-700'}`}>
            {secondsLeft > 0 ? `수령 마감까지 ${minutes}:${seconds}` : '수령 시간이 지났습니다 — 로봇이 돌아갑니다'}
          </p>
        )}
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => dialogRef.current?.close()}>
            {byButton ? "닫기 (배송 목록의 '받았습니다'로도 수령할 수 있음)" : "닫기 (배송 목록의 '수령 마커'로 다시 열 수 있음)"}
          </Button>
        </div>
      </div>
    </dialog>
  )
}
