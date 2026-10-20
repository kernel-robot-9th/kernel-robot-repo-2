// =============================================================================
// 파일   : src/features/maps/LocationPicker.tsx
// 역할   : 맵에서 찍은 위치·방향을 장소로 저장하는 패널 (관리자) — 새 장소 등록 또는 기존 장소 좌표 바꾸기
// 작성일 : 2026-10-19
// 구성   :
//   - PickedPose      찍은 값 (맵 좌표, 미터·라디안)
//   - LocationPicker  좌표 표시·직접 고치기 + 저장 대상 선택 + 저장
// 찍는 동작(누르기 = 위치, 누른 채 끌기 = 방향)은 pages/MapView.tsx가 맡는다
// =============================================================================
import { useState } from 'react'
import { useLocationMutations, useLocations } from '../../api/hooks'
import type { MapInfo } from '../../api/types'
import { Button, Input, Label, Select } from '../../components/ui'

export interface PickedPose {
  map_id: number
  x_m: number
  y_m: number
  yaw_rad: number
}

const NEW_LOCATION = 'new'
const round2 = (value: number) => Math.round(value * 100) / 100
const toDegrees = (radians: number) => Math.round((radians * 180) / Math.PI)

/** [입력] map: 지금 보는 맵 / canPick: 이미지가 있어 찍을 수 있는지 / picked: 찍은 값 / onPickedChange: 값 고치기·지우기 */
export function LocationPicker({ map, canPick, picked, onPickedChange }: {
  map: MapInfo
  canPick: boolean
  picked: PickedPose | null
  onPickedChange: (picked: PickedPose | null) => void
}) {
  const locations = useLocations()
  const { create, update } = useLocationMutations()
  const [target, setTarget] = useState<string>(NEW_LOCATION)
  const [name, setName] = useState('')
  const [notice, setNotice] = useState('')

  if (!canPick) {
    return (
      <div className="rounded border border-slate-200 bg-white p-3 text-sm text-slate-500">
        이 맵에는 이미지가 없어 장소를 찍을 수 없습니다. 맵 탭에서 맵 파일(yaml + pgm/png)을 올려 주세요.
      </div>
    )
  }

  const setField = (field: 'x_m' | 'y_m' | 'yaw_rad', text: string) => {
    const value = Number(text)
    if (picked && text !== '' && Number.isFinite(value)) onPickedChange({ ...picked, [field]: value })
  }
  const isNew = target === NEW_LOCATION
  const saving = create.isPending || update.isPending
  const save = () => {
    if (!picked) return
    const pose = { map_id: map.id, map_x_m: round2(picked.x_m), map_y_m: round2(picked.y_m), map_yaw_rad: round2(picked.yaw_rad) }
    const done = (savedName: string) => {
      setNotice(`'${savedName}' 좌표를 저장했습니다.`)
      setName('')
      onPickedChange(null)
    }
    if (isNew) {
      create.mutate({ name: name.trim(), ...pose }, { onSuccess: created => done(created.name) })
    } else {
      update.mutate({ id: Number(target), body: pose }, { onSuccess: updated => done(updated.name) })
    }
  }

  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-3 text-sm">
      <h2 className="font-medium">장소 찍기</h2>
      {notice && !picked && <p className="rounded bg-green-50 px-2 py-1 text-green-800">{notice}</p>}
      {!picked ? (
        <p className="text-slate-500">맵을 누르면 위치, 누른 채 끌면 로봇이 도착해 바라볼 방향이 정해집니다.</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Label text="x (m)"><Input type="number" step="0.01" value={round2(picked.x_m)} onChange={e => setField('x_m', e.target.value)} /></Label>
            <Label text="y (m)"><Input type="number" step="0.01" value={round2(picked.y_m)} onChange={e => setField('y_m', e.target.value)} /></Label>
            <Label text="yaw (rad)"><Input type="number" step="0.01" value={round2(picked.yaw_rad)} onChange={e => setField('yaw_rad', e.target.value)} /></Label>
          </div>
          <p className="text-xs text-slate-500">방향 {toDegrees(picked.yaw_rad)}° (0° = 맵 x축, 반시계 +)</p>
          <Label text="저장할 곳">
            <Select value={target} onChange={e => setTarget(e.target.value)}>
              <option value={NEW_LOCATION}>새 장소</option>
              {(locations.data ?? []).map(l => (
                <option key={l.id} value={l.id}>{l.name}{l.map_x_m == null ? ' (좌표 없음)' : ''}</option>
              ))}
            </Select>
          </Label>
          {isNew && <Label text="장소 이름"><Input value={name} onChange={e => setName(e.target.value)} placeholder="301호" /></Label>}
          <div className="flex gap-2">
            <Button disabled={saving || (isNew && name.trim() === '')} onClick={save}>{isNew ? '장소 등록' : '좌표 바꾸기'}</Button>
            <Button variant="secondary" onClick={() => onPickedChange(null)}>취소</Button>
          </div>
        </>
      )}
    </div>
  )
}
