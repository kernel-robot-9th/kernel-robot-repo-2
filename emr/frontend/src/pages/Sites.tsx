// =============================================================================
// 파일   : src/pages/Sites.tsx
// 역할   : 장소·맵·로봇 마스터 — 세 탭. 장소 등록(좌표+맵), 로봇 등록·상태 변경, 맵 조회
//          조회는 누구나, 등록·수정·삭제 버튼은 관리자에게만 보인다 (백엔드도 403)
// 작성일 : 2026-10-14
// 구성   :
//   - LocationsTab   POST/PATCH/DELETE /locations. 관리자 메모("4인실 왼쪽" 같은 설명)는 관리자에게만 보이고 칸을 벗어나면 저장 (2026-10-30)
//   - AdminNoteInput 관리자 메모 한 칸
//   - MapsTab        맵 파일(yaml + pgm/png) 업로드·교체·삭제 (관리자, 2026-10-19). 장소 찍기는 맵 화면
//   - RobotsTab      POST/PATCH/DELETE /robots, 로봇 API 키 발급·폐기 (관리자, 2026-10-19), 복귀 장소는 2026-10-27 없앰(팀원 FMS가 정함),
//                    로봇 서버 주소 입력·claim 때 받은 배터리·오염도 보기 (2026-10-23)
//   - BedsideTab     병상 단말 등록·병실·키 발급·폐기·삭제 (관리자만, 2026-10-22) — 환자가 /bedside 화면에서 비품 요청
//   - Sites          탭 전환
// =============================================================================
import { useState } from 'react'
import {
  useBedsideDeviceMutations, useBedsideDevices,
  useIsAdmin, useLocationMutations, useLocations, useMapMutations, useMaps, useMe, useRobotMutations, useRobots,
} from '../api/hooks'
import type { BedsideApiKey, BedsideDevice, Location, Robot, RobotApiKey, RobotStatus, RobotType } from '../api/types'
import { ROBOT_STATUS_LABEL, ROBOT_TYPE_LABEL } from '../api/types'
import { Badge, Button, Input, Label, LoadError, PageTitle, Select, Table, Td, Th } from '../components/ui'
import { RobotApiKeyDialog } from '../features/robots/RobotApiKeyDialog'
import { formatDate, formatTime } from '../lib/dateFormat'

// ---------- 장소 ----------
/** 관리자 메모 한 칸 — 칸을 벗어날 때 바뀌었으면 저장, 비우면 지운다. [입력] location [출력] 입력 칸 */
function AdminNoteInput({ location }: { location: Location }) {
  const { update } = useLocationMutations()
  const saved = location.admin_note ?? ''
  const [value, setValue] = useState(saved)
  const save = () => {
    const note = value.trim()
    if (note !== saved) update.mutate({ id: location.id, body: { admin_note: note } })
  }
  return (
    <Input value={value} maxLength={64} placeholder="예: 4인실 왼쪽" aria-label={`${location.name} 관리자 메모`}
      onChange={e => setValue(e.target.value)} onBlur={save} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} />
  )
}

function LocationsTab() {
  const locations = useLocations()
  const maps = useMaps()
  const { create, remove } = useLocationMutations()
  const isAdmin = useIsAdmin()
  const [form, setForm] = useState<Omit<Location, 'id'>>({ name: '', map_id: null, map_x_m: null, map_y_m: null, map_yaw_rad: 0, robot_dest: null, admin_note: null })

  // 좌표 세 값은 함께 있거나 함께 없어야 한다 (백엔드 CHECK)
  const hasCoords = form.map_x_m != null && form.map_y_m != null && form.map_yaw_rad != null
  const valid = form.name !== '' && (hasCoords ? form.map_id != null : form.map_x_m == null && form.map_y_m == null)

  const num = (v: string): number | null => (v === '' ? null : Number(v))
  const mapName = new Map((maps.data ?? []).map(m => [m.id, m.name]))

  return (
    <div className="space-y-4">
      {isAdmin && (
        <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
          <div className="grid grid-cols-7 gap-3">
            <Label text="이름"><Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="301호" /></Label>
            <Label text="맵">
              <Select value={form.map_id ?? ''} onChange={e => setForm(f => ({ ...f, map_id: num(e.target.value) }))}>
                <option value="">없음</option>
                {(maps.data ?? []).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
              </Select>
            </Label>
            <Label text="x (m)"><Input type="number" step="0.01" value={form.map_x_m ?? ''} onChange={e => setForm(f => ({ ...f, map_x_m: num(e.target.value) }))} /></Label>
            <Label text="y (m)"><Input type="number" step="0.01" value={form.map_y_m ?? ''} onChange={e => setForm(f => ({ ...f, map_y_m: num(e.target.value) }))} /></Label>
            <Label text="yaw (rad)"><Input type="number" step="0.01" value={form.map_yaw_rad ?? ''} onChange={e => setForm(f => ({ ...f, map_yaw_rad: num(e.target.value) }))} /></Label>
            <Label text="로봇 목적지"><Input value={form.robot_dest ?? ''} onChange={e => setForm(f => ({ ...f, robot_dest: e.target.value.trim() || null }))} placeholder="PHARMACY" /></Label>
            <Label text="관리자 메모"><Input value={form.admin_note ?? ''} maxLength={64} onChange={e => setForm(f => ({ ...f, admin_note: e.target.value || null }))} placeholder="4인실 왼쪽" /></Label>
          </div>
          <div className="flex items-center gap-3">
            <Button disabled={!valid || create.isPending} onClick={() => create.mutate(form, { onSuccess: () => setForm(f => ({ ...f, name: '', admin_note: null })) })}>
              장소 등록
            </Button>
            {!valid && form.name !== '' && <span className="text-xs text-slate-500">좌표를 넣으려면 x·y·yaw·맵 네 값이 모두 필요합니다</span>}
          </div>
        </div>
      )}
      {locations.isError ? (
        <LoadError what="장소 목록" error={locations.error} onRetry={() => void locations.refetch()} />
      ) : (
        <Table>
          <thead><tr><Th>이름</Th>{isAdmin && <Th>관리자 메모</Th>}<Th>맵</Th><Th>x (m)</Th><Th>y (m)</Th><Th>yaw (rad)</Th><Th>로봇 목적지</Th>{isAdmin && <Th>{' '}</Th>}</tr></thead>
          <tbody>
            {(locations.data ?? []).map(l => (
              <tr key={l.id}>
                <Td>{l.name}</Td>
                {isAdmin && <Td><AdminNoteInput key={`${l.id}-${l.admin_note ?? ''}`} location={l} /></Td>}
                <Td>{l.map_id == null ? <span className="text-slate-400">—</span> : mapName.get(l.map_id) ?? `#${l.map_id}`}</Td>
                <Td>{l.map_x_m ?? <span className="text-amber-600">좌표 없음</span>}</Td>
                <Td>{l.map_y_m ?? ''}</Td>
                <Td>{l.map_yaw_rad ?? ''}</Td>
                <Td>{l.robot_dest ? <code className="text-xs">{l.robot_dest}</code> : <span className="text-slate-400">—</span>}</Td>
                {isAdmin && <Td><Button variant="danger" onClick={() => { if (confirm(`'${l.name}' 장소를 삭제할까요?`)) remove.mutate(l.id) }}>삭제</Button></Td>}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  )
}

// ---------- 맵 ----------
const YAML_ACCEPT = '.yaml,.yml'
const IMAGE_ACCEPT = '.pgm,.png,image/png'

/** 맵 파일 두 개(yaml·이미지) 고르기. [입력] onChange(yaml, image) — 둘 다 골라야 값이 생긴다 */
function MapFileInputs({ onChange }: { onChange: (mapYaml: File | null, mapImage: File | null) => void }) {
  const [mapYaml, setMapYaml] = useState<File | null>(null)
  const [mapImage, setMapImage] = useState<File | null>(null)
  return (
    <>
      <Label text="map yaml (.yaml)">
        <input type="file" accept={YAML_ACCEPT} className="block w-56 text-sm"
          onChange={e => { const file = e.target.files?.[0] ?? null; setMapYaml(file); onChange(file, mapImage) }} />
      </Label>
      <Label text="맵 이미지 (.pgm · .png)">
        <input type="file" accept={IMAGE_ACCEPT} className="block w-56 text-sm"
          onChange={e => { const file = e.target.files?.[0] ?? null; setMapImage(file); onChange(mapYaml, file) }} />
      </Label>
    </>
  )
}

function MapsTab() {
  const maps = useMaps()
  const isAdmin = useIsAdmin()
  const { upload, replaceFiles, remove } = useMapMutations()
  const [name, setName] = useState('')
  const [files, setFiles] = useState<{ mapYaml: File | null; mapImage: File | null }>({ mapYaml: null, mapImage: null })
  const [formKey, setFormKey] = useState(0)   // 등록 후 파일 칸을 비우려고 다시 그린다
  const [replaceTargetId, setReplaceTargetId] = useState<number | null>(null)
  const [replaceFilesPicked, setReplaceFilesPicked] = useState<{ mapYaml: File | null; mapImage: File | null }>({ mapYaml: null, mapImage: null })

  const submitUpload = () => {
    if (!files.mapYaml || !files.mapImage) return
    upload.mutate({ name: name.trim(), mapYaml: files.mapYaml, mapImage: files.mapImage }, {
      onSuccess: () => { setName(''); setFiles({ mapYaml: null, mapImage: null }); setFormKey(key => key + 1) },
    })
  }
  const submitReplace = (mapId: number, mapName: string) => {
    const { mapYaml, mapImage } = replaceFilesPicked
    if (!mapYaml || !mapImage) return
    if (!confirm(`'${mapName}' 맵 파일을 바꿀까요? 장소 좌표는 그대로입니다 — 맵 원점이 바뀌었다면 장소를 맵 화면에서 다시 찍어야 합니다.`)) return
    replaceFiles.mutate({ id: mapId, mapYaml, mapImage }, { onSuccess: () => setReplaceTargetId(null) })
  }

  return (
    <div className="space-y-4">
      {isAdmin ? (
        <div key={formKey} className="space-y-2 rounded border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-end gap-3">
            <Label text="맵 이름"><Input value={name} onChange={e => setName(e.target.value)} placeholder="3병동" className="w-40" /></Label>
            <MapFileInputs onChange={(mapYaml, mapImage) => setFiles({ mapYaml, mapImage })} />
            <Button disabled={!name.trim() || !files.mapYaml || !files.mapImage || upload.isPending} onClick={submitUpload}>맵 등록</Button>
          </div>
          <p className="text-xs text-slate-500">
            로봇(Pinky)이 slam_toolbox로 만든 맵 파일(<code>map_saver_cli</code>의 .yaml과 .pgm)을 그대로 올리면 resolution·origin을 읽어 등록합니다.
            장소는 맵 화면에서 맵을 눌러 찍습니다.
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate-600">맵 등록·교체·삭제는 관리자만 할 수 있습니다.</p>
      )}
      {maps.isError ? (
        <LoadError what="맵 목록" error={maps.error} onRetry={() => void maps.refetch()} />
      ) : (
        <Table>
          <thead><tr><Th>이름</Th><Th>파일</Th><Th>이미지</Th><Th>resolution (m/px)</Th><Th>origin x (m)</Th><Th>origin y (m)</Th><Th>origin yaw (rad)</Th>{isAdmin && <Th>{' '}</Th>}</tr></thead>
          <tbody>
            {(maps.data ?? []).map(m => (
              <tr key={m.id}>
                <Td>{m.name}</Td>
                <Td className="font-mono">{m.file_name}</Td>
                <Td>{m.has_image ? <span>{m.image_file_name} <span className="text-xs text-slate-500">{m.image_width_px}×{m.image_height_px}px</span></span> : <span className="text-slate-400">없음</span>}</Td>
                <Td>{m.resolution_m_per_pixel}</Td><Td>{m.origin_x_m}</Td><Td>{m.origin_y_m}</Td><Td>{m.origin_yaw_rad}</Td>
                {isAdmin && (
                  <Td>
                    {replaceTargetId === m.id ? (
                      <div className="flex flex-wrap items-end gap-2">
                        <MapFileInputs onChange={(mapYaml, mapImage) => setReplaceFilesPicked({ mapYaml, mapImage })} />
                        <Button disabled={!replaceFilesPicked.mapYaml || !replaceFilesPicked.mapImage || replaceFiles.isPending} onClick={() => submitReplace(m.id, m.name)}>교체</Button>
                        <Button variant="secondary" onClick={() => setReplaceTargetId(null)}>취소</Button>
                      </div>
                    ) : (
                      <div className="flex gap-1">
                        <Button variant="secondary" onClick={() => { setReplaceFilesPicked({ mapYaml: null, mapImage: null }); setReplaceTargetId(m.id) }}>
                          {m.has_image ? '파일 교체' : '파일 올리기'}
                        </Button>
                        <Button variant="danger" onClick={() => { if (confirm(`'${m.name}' 맵을 삭제할까요?`)) remove.mutate(m.id) }}>삭제</Button>
                      </div>
                    )}
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  )
}

// ---------- 로봇 ----------
function RobotsTab() {
  const robots = useRobots()
  const { create, update, remove, issueApiKey, revokeApiKey } = useRobotMutations()
  const isAdmin = useIsAdmin()
  const [name, setName] = useState('')
  const [type, setType] = useState<RobotType>('amr')
  const [issuedKey, setIssuedKey] = useState<{ robotName: string; issued: RobotApiKey } | null>(null)

  const issueKey = (robot: Robot) => {
    if (robot.has_api_key && !confirm(`${robot.name}의 키를 다시 발급할까요? 지금 로봇(배송 실행기)에 설정된 키는 바로 쓸 수 없게 됩니다.`)) return
    issueApiKey.mutate(robot.id, { onSuccess: issued => setIssuedKey({ robotName: robot.name, issued }) })
  }

  return (
    <div className="space-y-4">
      {isAdmin && (
        <div className="flex items-end gap-3 rounded border border-slate-200 bg-white p-4">
          <Label text="이름"><Input value={name} onChange={e => setName(e.target.value)} placeholder="amr-1" className="w-40" /></Label>
          <Label text="종류 (등록 후 변경 불가)">
            <Select value={type} onChange={e => setType(e.target.value as RobotType)} className="w-40">
              <option value="amr">{ROBOT_TYPE_LABEL.amr}</option><option value="manipulator">{ROBOT_TYPE_LABEL.manipulator}</option>
            </Select>
          </Label>
          <Button disabled={!name || create.isPending} onClick={() => create.mutate({ name, robot_type: type, status: 'idle' }, { onSuccess: () => setName('') })}>
            로봇 등록
          </Button>
        </div>
      )}
      {robots.isError ? (
        <LoadError what="로봇 목록" error={robots.error} onRetry={() => void robots.refetch()} />
      ) : (
        <Table>
          <thead><tr><Th>이름</Th><Th>종류</Th><Th>상태</Th><Th>로봇 서버</Th><Th>배터리·오염도 (claim 때 확인)</Th><Th>로봇 API 키</Th>{isAdmin && <><Th>상태 변경</Th><Th>{' '}</Th></>}</tr></thead>
          <tbody>
            {(robots.data ?? []).map(r => (
              <tr key={r.id}>
                <Td>{r.name}</Td>
                <Td>{ROBOT_TYPE_LABEL[r.robot_type]}</Td>
                <Td><Badge value={r.status} label={ROBOT_STATUS_LABEL[r.status]} /></Td>
                <Td>
                  {/* 팀원 Pinky API 주소 — claim 때 EMR이 GET {주소}/status로 배터리·오염도·주행 준비를 묻는다. 빈 칸 = 배송 안 맡음 (2026-10-23) */}
                  {isAdmin && r.robot_type === 'amr' ? (
                    <Input
                      key={r.robot_server_url ?? ''} defaultValue={r.robot_server_url ?? ''} placeholder="http://192.168.129.107:8080"
                      className="w-56" aria-label={`${r.name} 로봇 서버 주소`}
                      onBlur={e => {
                        const value = e.target.value.trim()
                        if (value && value !== r.robot_server_url) update.mutate({ id: r.id, body: { robot_server_url: value } })
                      }}
                    />
                  ) : (
                    <span className={r.robot_server_url ? 'font-mono text-xs' : 'text-slate-400'}>
                      {r.robot_server_url ?? (r.robot_type === 'amr' ? '없음 — 배송 안 맡음' : '—')}
                    </span>
                  )}
                </Td>
                <Td>
                  {/* claim 때 로봇 서버에서 받은 마지막 값. 기준 밖이면 EMR이 새 배송을 주지 않는다 (2026-10-23) */}
                  {r.status_report ? (
                    <span>
                      배터리 {r.status_report.battery_percent.toFixed(0)}% · 오염도 {r.status_report.contamination_percent.toFixed(0)}
                      <span className="ml-1 text-xs text-slate-500">{formatTime(r.status_report.reported_at)}</span>
                    </span>
                  ) : (
                    <span className="text-slate-400">{r.robot_type === 'amr' ? '아직 받은 적 없음' : '—'}</span>
                  )}
                </Td>
                <Td>
                  {r.has_api_key && r.api_key_issued_at
                    ? <span className="text-green-700">발급됨 <span className="text-xs text-slate-500">{formatDate(r.api_key_issued_at)}</span></span>
                    : <span className="text-slate-400">없음</span>}
                  {isAdmin && (
                    <span className="ml-2 inline-flex gap-1">
                      <Button variant="secondary" disabled={issueApiKey.isPending} onClick={() => issueKey(r)}>{r.has_api_key ? '재발급' : '발급'}</Button>
                      {r.has_api_key && (
                        <Button variant="secondary" disabled={revokeApiKey.isPending}
                          onClick={() => { if (confirm(`${r.name}의 키를 폐기할까요? 로봇이 배송을 가져가거나 수령 확인을 할 수 없게 됩니다.`)) revokeApiKey.mutate(r.id) }}>
                          폐기
                        </Button>
                      )}
                    </span>
                  )}
                </Td>
                {isAdmin && <>
                  <Td>
                    <Select value={r.status} className="w-32" onChange={e => update.mutate({ id: r.id, body: { status: e.target.value as RobotStatus } })}>
                      {(Object.keys(ROBOT_STATUS_LABEL) as RobotStatus[]).map(s => <option key={s} value={s}>{ROBOT_STATUS_LABEL[s]}</option>)}
                    </Select>
                  </Td>
                  <Td><Button variant="danger" onClick={() => { if (confirm(`${r.name} 삭제?`)) remove.mutate(r.id) }}>삭제</Button></Td>
                </>}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {issuedKey && <RobotApiKeyDialog robotName={issuedKey.robotName} issued={issuedKey.issued} onClose={() => setIssuedKey(null)} />}
    </div>
  )
}

// ---------- 병상 단말 (2026-10-22) ----------
function BedsideTab() {
  const isAdmin = useIsAdmin()
  const devices = useBedsideDevices()
  const locations = useLocations()
  const { create, update, remove, issueApiKey, revokeApiKey } = useBedsideDeviceMutations()
  const [name, setName] = useState('')
  const [roomId, setRoomId] = useState<number | ''>('')
  const [issuedKey, setIssuedKey] = useState<{ name: string; issued: BedsideApiKey } | null>(null)
  const bedsideUrl = `${window.location.origin}/bedside`

  if (!isAdmin) return <p className="text-sm text-slate-500">병상 단말 관리는 관리자만 할 수 있습니다.</p>

  const issueKey = (device: BedsideDevice) => {
    if (device.has_api_key && !confirm(`${device.name}의 키를 다시 발급할까요? 지금 병상 화면에 넣은 키는 바로 쓸 수 없게 됩니다.`)) return
    issueApiKey.mutate(device.id, { onSuccess: issued => setIssuedKey({ name: device.name, issued }) })
  }
  const roomOptions = (locations.data ?? []).map(room => (
    <option key={room.id} value={room.id}>{room.name}{room.map_x_m == null ? ' (좌표 없음)' : ''}</option>
  ))

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        환자가 병상 태블릿에서 비품을 요청하면 간호사 승인 없이 바로 로봇이 가져갑니다(병상당 진행 중 1건, 환자용 품목만).
        병상 화면 주소는 <code className="rounded bg-slate-100 px-1">{bedsideUrl}</code>이고, 처음 열 때 여기서 발급한 키를 넣습니다.
      </p>
      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-4">
        <Label text="병상 이름"><Input value={name} onChange={e => setName(e.target.value)} placeholder="301호-1" className="w-40" /></Label>
        <Label text="병실 (배송 목적지)">
          <Select value={roomId} onChange={e => setRoomId(e.target.value ? Number(e.target.value) : '')} className="w-48">
            <option value="">선택하세요</option>
            {roomOptions}
          </Select>
        </Label>
        <Button disabled={!name || roomId === '' || create.isPending}
          onClick={() => roomId !== '' && create.mutate({ name, location_id: roomId }, { onSuccess: () => { setName(''); setRoomId('') } })}>
          병상 등록
        </Button>
      </div>
      {devices.isError ? (
        <LoadError what="병상 단말 목록" error={devices.error} onRetry={() => void devices.refetch()} />
      ) : (
        <Table>
          <thead><tr><Th>병상</Th><Th>병실</Th><Th>단말 키</Th><Th>{' '}</Th></tr></thead>
          <tbody>
            {devices.isPending && <tr><td colSpan={4} className="px-3 py-2 text-slate-500">불러오는 중…</td></tr>}
            {(devices.data ?? []).map(device => (
              <tr key={device.id}>
                <Td>{device.name}</Td>
                <Td>
                  <Select value={device.location_id} className="w-48" aria-label={`${device.name} 병실`}
                    onChange={e => update.mutate({ id: device.id, body: { location_id: Number(e.target.value) } })}>
                    {roomOptions}
                  </Select>
                </Td>
                <Td>
                  {device.has_api_key && device.api_key_issued_at
                    ? <span className="text-green-700">발급됨 <span className="text-xs text-slate-500">{formatDate(device.api_key_issued_at)}</span></span>
                    : <span className="text-slate-400">없음 (병상 화면을 쓸 수 없음)</span>}
                  <span className="ml-2 inline-flex gap-1">
                    <Button variant="secondary" disabled={issueApiKey.isPending} onClick={() => issueKey(device)}>{device.has_api_key ? '재발급' : '발급'}</Button>
                    {device.has_api_key && (
                      <Button variant="secondary" disabled={revokeApiKey.isPending}
                        onClick={() => { if (confirm(`${device.name}의 키를 폐기할까요? 병상 화면에서 요청할 수 없게 됩니다.`)) revokeApiKey.mutate(device.id) }}>
                        폐기
                      </Button>
                    )}
                  </span>
                </Td>
                <Td><Button variant="danger" onClick={() => { if (confirm(`${device.name} 삭제?`)) remove.mutate(device.id) }}>삭제</Button></Td>
              </tr>
            ))}
            {!devices.isPending && (devices.data ?? []).length === 0 && (
              <tr><td colSpan={4} className="px-3 py-2 text-slate-500">등록된 병상 단말이 없습니다</td></tr>
            )}
          </tbody>
        </Table>
      )}
      {issuedKey && (
        <RobotApiKeyDialog robotName={issuedKey.name} issued={issuedKey.issued} title="병상 단말 키" onClose={() => setIssuedKey(null)}
          help={<>병상 태블릿에서 <code>{bedsideUrl}</code>를 열고 이 키를 입력합니다. 키는 그 태블릿 브라우저에만 저장됩니다.</>} />
      )}
    </div>
  )
}

const TABS = [
  { key: 'locations', label: '장소', el: <LocationsTab /> },
  { key: 'maps', label: '맵', el: <MapsTab /> },
  { key: 'robots', label: '로봇', el: <RobotsTab /> },
  { key: 'bedside', label: '병상 단말', el: <BedsideTab /> },
] as const
type TabKey = (typeof TABS)[number]['key']

export function Sites() {
  const [tab, setTab] = useState<TabKey>('locations')
  const me = useMe()
  const isAdmin = useIsAdmin()
  return (
    <div className="space-y-4">
      <PageTitle>환경 설정</PageTitle>
      {me.data && !isAdmin && (
        <p className="text-sm text-slate-500">조회만 할 수 있습니다. 환경 설정(장소·맵·로봇·병상) 등록·수정·삭제는 관리자만 할 수 있습니다.</p>
      )}
      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm ${tab === t.key ? 'border-b-2 border-blue-600 font-medium text-blue-700' : 'text-slate-600'}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {TABS.find(t => t.key === tab)?.el}
    </div>
  )
}
