// =============================================================================
// 파일   : src/pages/MapView.tsx
// 역할   : 맵 화면 — 올린 맵 이미지(실제 크기) 위에 장소 마커와 운반 로봇 위치, 지도 아래 로봇 카드(배터리·오염도). 관리자는 맵을 눌러 장소 위치·방향을 찍는다 (2026-10-19)
// 작성일 : 2026-10-14
// 구성   :
//   - toSvgPoint     화면 좌표 → SVG(이미지 픽셀) 좌표
//   - RobotCards     지도 아래 로봇 카드 — 이름·상태·위치·배터리·오염도 막대 (2026-10-30)
//   - MapView        맵 선택 → 이미지 + 장소 마커 + 운반 로봇 위치(주황) + 로봇 카드 + (관리자) 찍기 + 로봇 상태 패널
// 좌표 변환은 features/maps/mapGeometry.ts (ROS map_server 규칙). 이미지가 없는 맵은 격자로 그린다
// 로봇 위치(2026-10-29)는 팀원 FMS가 1초마다 보낸 마지막 값(GET /robot-positions) — 그 응답의 map_id 맵을 볼 때만 그린다
// =============================================================================
import { useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { apiUrl } from '../api/client'
import { useIsAdmin, useLocations, useMaps, useRobotPositions, useRobots } from '../api/hooks'
import { ROBOT_TYPE_LABEL } from '../api/types'
import { ROBOT_STATUS_LABEL } from '../api/types'
import type { RobotPosition } from '../api/types'
import { Badge, LoadError, PageTitle, Select } from '../components/ui'
import { LocationPicker } from '../features/maps/LocationPicker'
import type { PickedPose } from '../features/maps/LocationPicker'
import { headingToSvgVector, mapImageSize, metersToPixel, pixelToMeters, svgVectorToHeading } from '../features/maps/mapGeometry'

const DRAG_MIN_PX_ON_SCREEN = 6   // 이보다 짧게 끌면 방향 없이 위치만 찍은 것으로 본다
const SMOOTH_IMAGE_MIN_WIDTH_PX = 1000   // 이보다 큰 이미지(평면도)는 줄일 때 글자가 깨지지 않게 부드럽게, 작은 SLAM 맵은 픽셀 그대로
const ROBOT_COLOR = '#ea580c'
const STALE_ROBOT_COLOR = '#94a3b8'
const LOW_BATTERY_PERCENT = 20         // FMS pharmacy_min_battery — 이 값 이하면 약제실에 가지 못한다
const HIGH_CONTAMINATION_PERCENT = 50  // 4인실 한 번 다녀온 만큼
// FMS 로봇 state → 화면 글자 (fms/API.md 상태 값). 모르는 값은 그대로 보여 준다
const ROBOT_STATE_LABEL: Record<string, string> = {
  idle: '대기', reserved: '배차됨', moving: '이동', waiting: '길 막힘', docking: '정밀 주차', loading: '적재 대기',
  spinning: '병실 도착', pausing: '잠시 멈춤', decon: '오염 제거', charging: '충전', error: '멈춤',
}

/** 0~100 막대 한 줄. [입력] label, percent(null이면 "—"), tone: 막대 색 Tailwind 클래스 */
function PercentBar({ label, percent, tone }: { label: string; percent: number | null; tone: string }) {
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-500">
        <span>{label}</span>
        <span className="font-medium text-slate-700">{percent == null ? '—' : `${Math.round(percent)}%`}</span>
      </div>
      <div className="mt-0.5 h-1.5 rounded bg-slate-100">
        <div className={`h-1.5 rounded ${tone}`} style={{ width: `${percent ?? 0}%` }} />
      </div>
    </div>
  )
}

/** 지도 아래 로봇 카드 (2026-10-30). [입력] robots: 이 지도에 그리는 로봇 */
function RobotCards({ robots }: { robots: RobotPosition[] }) {
  if (robots.length === 0) return null
  return (
    <div className="px-2 pt-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {robots.map(robot => {
          const name = robot.robot_name ?? robot.fms_robot_name ?? `FMS ${robot.fms_robot_number}`
          const battery = robot.battery_percent
          const contamination = robot.contamination_percent
          const stateLabel = robot.state ? (ROBOT_STATE_LABEL[robot.state] ?? robot.state) : '—'
          return (
            <div key={robot.fms_robot_number}
              className={`space-y-2 rounded border p-3 ${robot.is_stale ? 'border-slate-200 bg-slate-50 opacity-70' : 'border-slate-200 bg-white'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: robot.is_stale ? STALE_ROBOT_COLOR : ROBOT_COLOR }} />
                  {name}
                </span>
                <span className="text-xs text-slate-500">{robot.is_stale ? '연결 끊김' : stateLabel}</span>
              </div>
              <p className="text-xs text-slate-500">{robot.place ?? '위치 모름'}</p>
              <PercentBar label="배터리" percent={battery}
                tone={battery != null && battery <= LOW_BATTERY_PERCENT ? 'bg-red-500' : 'bg-green-500'} />
              <PercentBar label="오염도" percent={contamination}
                tone={contamination == null || contamination === 0 ? 'bg-green-500'
                  : contamination >= HIGH_CONTAMINATION_PERCENT ? 'bg-red-500' : 'bg-amber-400'} />
            </div>
          )
        })}
      </div>
      <p className="pt-1 text-xs text-slate-400">배터리·오염도는 FMS가 계산한 값입니다.</p>
    </div>
  )
}

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
  const robotPositions = useRobotPositions()
  const isAdmin = useIsAdmin()
  const [mapId, setMapId] = useState<number | ''>('')
  const [picked, setPicked] = useState<PickedPose | null>(null)
  const dragStart = useRef<{ px: number; py: number; clientX: number; clientY: number } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  // 고르지 않았으면 운반 로봇이 있는 지도(FMS 지도)를 먼저, 없으면 첫 지도 (2026-10-29)
  const defaultMapId = (maps.data ?? []).find(m => m.id === robotPositions.data?.map_id)?.id ?? maps.data?.[0]?.id
  const map = (maps.data ?? []).find(m => m.id === (mapId === '' ? defaultMapId : mapId))
  const size = map ? mapImageSize(map) : null
  const canPick = isAdmin && !!map?.has_image
  const marks = map
    ? (locations.data ?? []).filter(l => l.map_id === map.id && l.map_x_m != null && l.map_y_m != null)
    : []
  const robotMarks = map && robotPositions.data?.map_id === map.id ? robotPositions.data.robots : []
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
                    width={size.width_px} height={size.height_px}
                    style={{ imageRendering: size.width_px >= SMOOTH_IMAGE_MIN_WIDTH_PX ? 'auto' : 'pixelated' }}
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
                {robotMarks.map(robot => {
                  const { px, py } = metersToPixel(robot.map_x_m, robot.map_y_m, map)
                  const { dx, dy } = headingToSvgVector(robot.map_yaw_rad, map)
                  const color = robot.is_stale ? STALE_ROBOT_COLOR : ROBOT_COLOR
                  const name = robot.robot_name ?? robot.fms_robot_name ?? `FMS ${robot.fms_robot_number}`
                  return (
                    // 1초마다 오는 위치 사이를 부드럽게 움직인다 (CSS transform이라 transition이 걸린다)
                    <g
                      key={robot.fms_robot_number} pointerEvents="none"
                      style={{ transform: `translate(${px}px, ${py}px)`, transition: 'transform 1s linear' }}
                    >
                      <circle r={unit * 1.2} fill={color} stroke="white" strokeWidth={unit * 0.3} />
                      <g transform={`rotate(${(Math.atan2(dy, dx) * 180) / Math.PI})`}>
                        <polygon points={`${unit * 0.85},0 ${-unit * 0.5},${unit * 0.55} ${-unit * 0.5},${-unit * 0.55}`} fill="white" />
                      </g>
                      <text x={unit * 1.4} y={unit * 2.4} fontSize={unit * 1.4} fontWeight={600} fill={color} stroke="white" strokeWidth={unit * 0.35} paintOrder="stroke">
                        {robot.is_stale ? `${name} (연결 끊김)` : name}
                      </text>
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
            <RobotCards robots={robotMarks} />
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
              <p className="pt-2 text-xs text-slate-400">
                {robotMarks.length > 0 ? '주황 점이 운반 로봇의 지금 위치입니다.' : '이 지도에는 운반 로봇 위치가 아직 없습니다.'}
              </p>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
