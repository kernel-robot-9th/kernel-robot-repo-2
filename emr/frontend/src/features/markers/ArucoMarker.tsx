// =============================================================================
// 파일   : src/features/markers/ArucoMarker.tsx
// 역할   : ArUco 마커 그림 (SVG) — 화면 미리보기와 인쇄에 같이 쓴다
// 작성일 : 2026-10-16
// 구성   :
//   - QUIET_ZONE_CELLS  마커 둘레 흰 여백 (칸 수). 여백이 없으면 카메라가 테두리를 못 찾는다
//   - ArucoMarker       번호 → SVG. 크기는 className(화면) 또는 markerSideMm(인쇄, 검정 테두리 바깥 기준)
// =============================================================================
import { ARUCO_MARKER_CELLS, arucoMarkerCells } from './arucoDictionary'

export const QUIET_ZONE_CELLS = 1

/** [입력] arucoMarkerId: 0~249 (간호사 0~49, 일회용 수령 50~249) / markerSideMm: 인쇄용 실제 크기(검정 정사각형 한 변, mm) / className: 화면용 크기 */
export function ArucoMarker({ arucoMarkerId, markerSideMm, className }: {
  arucoMarkerId: number
  markerSideMm?: number
  className?: string
}) {
  const totalCells = ARUCO_MARKER_CELLS + QUIET_ZONE_CELLS * 2
  const totalSideMm = markerSideMm === undefined ? undefined : `${(markerSideMm * totalCells) / ARUCO_MARKER_CELLS}mm`
  const cells = arucoMarkerCells(arucoMarkerId)
  return (
    <svg
      role="img" aria-label={`ArUco 4x4 마커 ${arucoMarkerId}번`}
      viewBox={`0 0 ${totalCells} ${totalCells}`} width={totalSideMm} height={totalSideMm}
      shapeRendering="crispEdges" className={className}
    >
      <rect width={totalCells} height={totalCells} fill="#fff" />
      {cells.flatMap((rowCells, row) => rowCells.map((isBlack, column) => isBlack && (
        <rect key={`${row}-${column}`} x={column + QUIET_ZONE_CELLS} y={row + QUIET_ZONE_CELLS} width={1} height={1} fill="#000" />
      )))}
    </svg>
  )
}
