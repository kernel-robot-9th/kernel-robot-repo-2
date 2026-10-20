// =============================================================================
// 파일   : src/features/markers/MarkerPrintDialog.tsx
// 역할   : 간호사 마커 카드 보기·인쇄 — 이름·사번·마커를 실제 크기로 한 장에
// 작성일 : 2026-10-16
// 구성   :
//   - PRINT_MARKER_SIDE_MM  인쇄할 마커 크기 (검정 정사각형 한 변)
//   - MarkerPrintDialog     <dialog>를 body에 바로 붙인다 — 인쇄할 때 index.css가 앱(#root)을 숨기고 이 카드만 찍는다
// =============================================================================
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { Nurse } from '../../api/types'
import { Button } from '../../components/ui'
import { ArucoMarker } from './ArucoMarker'

// [검토 필요] 마커 크기는 가정값이다. 로봇 카메라 거리·해상도와 자세 추정에 쓰는 마커 크기를 로봇 부서와 맞춰야 한다
export const PRINT_MARKER_SIDE_MM = 50

/** [입력] nurse: aruco_marker_id가 있는 간호사 / onClose: 닫기 */
export function MarkerPrintDialog({ nurse, onClose }: { nurse: Nurse & { aruco_marker_id: number }; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  return createPortal(
    <dialog
      ref={dialogRef} onClose={onClose} aria-labelledby="marker-dialog-title"
      className="marker-print m-auto rounded-lg p-0 shadow-xl backdrop:bg-slate-900/40 print:shadow-none"
    >
      <div className="space-y-4 p-6">
        <div className="flex flex-col items-center gap-2 rounded border border-dashed border-slate-300 px-8 py-6 print:border-slate-400">
          <h2 id="marker-dialog-title" className="text-lg font-semibold">{nurse.name}</h2>
          <p className="font-mono text-sm text-slate-600">{nurse.employee_no} · 마커 {nurse.aruco_marker_id}번 (4x4_50)</p>
          <ArucoMarker arucoMarkerId={nurse.aruco_marker_id} markerSideMm={PRINT_MARKER_SIDE_MM} />
        </div>
        <p className="max-w-sm text-xs text-slate-500 print:hidden">
          인쇄 설정에서 배율을 <b>100%(실제 크기)</b>로 두세요. 마커의 검정 정사각형 한 변이 {PRINT_MARKER_SIDE_MM}mm여야 합니다.
          마커 둘레의 흰 여백은 자르지 마세요.
        </p>
        <div className="flex justify-end gap-2 print:hidden">
          <Button variant="secondary" onClick={onClose}>닫기</Button>
          <Button onClick={() => window.print()}>인쇄</Button>
        </div>
      </div>
    </dialog>,
    document.body,
  )
}
