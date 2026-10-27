// =============================================================================
// 파일   : src/pages/MapView.tsx
// 역할   : 맵 화면 — 올린 맵 이미지(실제 크기) 위에 장소 마커. 관리자는 맵을 눌러 장소 위치·방향을 찍는다 (2026-10-19)
// 작성일 : 2026-10-14
// 구성   :
//   - toSvgPoint     화면 좌표 → SVG(이미지 픽셀) 좌표
//   - MapView        맵 선택 → 이미지 + 장소 마커 + (관리자) 찍기 + 로봇 상태 패널
// 좌표 변환은 features/maps/mapGeometry.ts (ROS map_server 규칙). 이미지가 없는 맵은 격자로 그린다
// =============================================================================
// [검토 필요] 로봇 실시간 위치(x·y)는 아직 백엔드에 없다 — 로드맵 3단계(로봇 상태 보고)에서 robots에 위치가 들어오면
//   장소와 같은 metersToPixel로 마커를 하나 더 그리면 된다.
import { useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { apiUrl } from '../api/client'
import { useIsAdmin, useLocations, useMaps, useRobots } from '../api/hooks'
import { ROBOT_TYPE_LABEL } from '../api/types'
import { ROBOT_STATUS_LABEL } from '../api/types'
import { Badge, LoadError, PageTitle, Select } from '../components/ui'
import { LocationPicker } from '../features/maps/LocationPicker'
import type { PickedPose } from '../features/maps/LocationPicker'
import { headingToSvgVector, mapImageSize, metersToPixel, pixelToMeters, svgVectorToHeading } from '../features/maps/mapGeometry'

const DRAG_MIN_PX_ON_SCREEN = 6   // 이보다 짧게 끌면 방향 없이 위치만 찍은 것으로 본다

/** 화면 좌표 → SVG 좌표(viewBox = 이미지 픽셀). [입력] svg, clientX, clientY [출력] { px, py } | null */
function toSvgPoint(svg: SVGSVGElement, clientX: number, clientY: number): { px: number; py: number } | null {
  const matrix = svg.getScreenCTM()
  if (!matrix) return null
  const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse())
  return { px: point.x, py: point.y }
}

export function MapView() {
  const maps = useMaps()
  const locations = useLocations()
  const robots = useRobots()
  const isAdmin = useIsAdmin()
  const [mapId, setMapId] = useState<number | ''>('')
  const [picked, setPicked] = useState<PickedPose | null>(null)
  const dragStart = useRef<{ px: number; py: number; clientX: number; clientY: number } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const map = (maps.data ?? []).find(m => m.id === (mapId === '' ? maps.data?.[0]?.id : mapId))
  const size = map ? mapImageSize(map) : null
  const canPick = isAdmin && !!map?.has_image
  const marks = map
    ? (locations.data ?? []).filter(l => l.map_id === map.id && l.map_x_m != null && l.map_y_m != null)
    : []
  // 맵 크기와 상관없이 마커가 화면에서 비슷한 크기로 보이게 이미지 크기에 비례
  const unit = size ? Math.max(size.width_px, size.height_px) / 70 : 1

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!canPick || !map || !size || !svgRef.current) return
    const point = toSvgPoint(svgRef.current, event.clientX, event.clientY)
    if (!point || point.px < 0 || point.py < 0 || point.px > size.width_px || point.py > size.height_px) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragStart.current = { ...point, clientX: event.clientX, clientY: event.clientY }
    const { x_m, y_m } = pixelToMeters(point.px, point.py, map)
    setPicked({ map_id: map.id, x_m, y_m, yaw_rad: 0 })
  }
  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const start = dragStart.current
    if (!start || !map || !svgRef.current) return
    if (Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY) < DRAG_MIN_PX_ON_SCREEN) return
    const point = toSvgPoint(svgRef.current, event.clientX, event.clientY)
    if (!point) return
    const yaw_rad = svgVectorToHeading(point.px - start.px, point.py - start.py, map)
    setPicked(current => current && { ...current, yaw_rad })
  }
  const onPointerUp = () => { dragStart.current = null }

  const pickedPixel = map && picked?.map_id === map.id ? metersToPixel(picked.x_m, picked.y_m, map) : null

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <PageTitle>병원 지도</PageTitle>
        <div className="w-64">
          <Select value={map?.id ?? ''} onChange={e => { setPicked(null); setMapId(e.target.value === '' ? '' : Number(e.target.value)) }}>
            {(maps.data ?? []).map(m => <option key={m.id} value={m.id}>{m.name} ({m.file_name})</option>)}
          </Select>
        </div>
      </div>
      {maps.isError ? (
        <LoadError what="병원 지도 목록" error={maps.error} onRetry={() => void maps.refetch()} />
      ) : (
        <div className="flex gap-4">
          <div className="flex-1 rounded border border-slate-200 bg-white p-2">
            {!map || !size ? (
              <p className="p-4 text-sm text-slate-500">등록된 병원 지도가 없습니다. 관리자에게 지도 등록을 요청해 주세요.</p>
            ) : (
              <svg
                ref={svgRef} viewBox={`0 0 ${size.width_px} ${size.height_px}`}
                className={`max-h-[75vh] w-full touch-none select-none ${canPick ? 'cursor-crosshair' : ''}`}
                onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
              >
                {map.has_image ? (
                  <image
                    href={apiUrl(`/maps/${map.id}/image?v=${encodeURIComponent(map.updated_at)}`)}
                    width={size.width_px} height={size.height_px} style={{ imageRendering: 'pixelated' }}
                  />
                ) : (
                  <>
                    <defs>
                      <pattern id="grid" width={40} height={40} patternUnits="userSpaceOnUse">
                        <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#e2e8f0" strokeWidth={1} />
                      </pattern>
                    </defs>
                    <rect width={size.width_px} height={size.height_px} fill="url(#grid)" />
                  </>
                )}
                {marks.map(l => {
                  const { px, py } = metersToPixel(l.map_x_m as number, l.map_y_m as number, map)
                  const { dx, dy } = headingToSvgVector(l.map_yaw_rad ?? 0, map)
                  return (
                    <g key={l.id} transform={`translate(${px} ${py})`} pointerEvents="none">
                      <line x1={0} y1={0} x2={dx * unit * 2.2} y2={dy * unit * 2.2} stroke="#2563eb" strokeWidth={unit * 0.3} />
                      <circle r={unit * 0.8} fill="#2563eb" stroke="white" strokeWidth={unit * 0.25} />
                      <text x={unit} y={-unit} fontSize={unit * 1.4} fill="#1e293b" stroke="white" strokeWidth={unit * 0.3} paintOrder="stroke">{l.name}</text>
                    </g>
                  )
                })}
                {pickedPixel && picked && (() => {
                  const { dx, dy } = headingToSvgVector(picked.yaw_rad, map)
                  return (
                    <g transform={`translate(${pickedPixel.px} ${pickedPixel.py})`} pointerEvents="none">
                      <line x1={0} y1={0} x2={dx * unit * 3} y2={dy * unit * 3} stroke="#dc2626" strokeWidth={unit * 0.35} />
                      <circle r={unit * 0.9} fill="#dc2626" stroke="white" strokeWidth={unit * 0.25} />
                    </g>
                  )
                })()}
              </svg>
            )}
            {map && isAdmin && (   /* 지도 파일·해상도·원점은 관리자 정보 (2026-10-27) */
              <p className="px-2 pt-2 text-xs text-slate-500">
                {map.file_name}{map.image_file_name ? ` · ${map.image_file_name} ${map.image_width_px}×${map.image_height_px}px` : ' · 이미지 없음(격자)'}
                {' '}· resolution {map.resolution_m_per_pixel} m/px · origin ({map.origin_x_m}, {map.origin_y_m}, {map.origin_yaw_rad}) · 장소 {marks.length}개
              </p>
            )}
          </div>

          <aside className="w-64 space-y-4">
            {isAdmin && map && (
              <LocationPicker
                map={map} canPick={canPick} picked={picked?.map_id === map.id ? picked : null}
                onPickedChange={setPicked}
              />
            )}
            <div className="space-y-2 rounded border border-slate-200 bg-white p-3">
              <h2 className="text-sm font-medium">운반·탑재 로봇</h2>
              {robots.isError && <LoadError what="로봇 목록" error={robots.error} onRetry={() => void robots.refetch()} />}
              {(robots.data ?? []).map(r => (
                <div key={r.id} className="flex items-center justify-between text-sm">
                  <span>{r.name} <span className="text-xs text-slate-400">{ROBOT_TYPE_LABEL[r.robot_type]}</span></span>
                  <Badge value={r.status} label={ROBOT_STATUS_LABEL[r.status]} />
                </div>
              ))}
              <p className="pt-2 text-xs text-slate-400">운반 로봇의 지금 위치는 아직 지도에 보이지 않습니다.</p>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
