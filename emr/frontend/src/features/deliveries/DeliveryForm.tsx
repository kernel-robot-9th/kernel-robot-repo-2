// =============================================================================
// 파일   : src/features/deliveries/DeliveryForm.tsx
// 역할   : 배송 예약 생성·변경 폼 — 목적지·예약 시각(미래)·품목(비품+수량, 예약 가능 수량 이하) 여러 줄
// 작성일 : 2026-10-14
// 구성   :
//   - ItemRow / WardRow  품목 한 줄 / 병동 한 곳(목적지 + 품목 줄) 상태
//   - toLocalInput/toIso datetime-local ↔ ISO 변환
//   - useNow             현재 시각 상태 (렌더 중 Date.now() 호출 대신)
//   - DeliveryForm       initial 없으면 POST /deliveries(병동 1곳)·POST /deliveries/multi(여러 병동), 있으면 PATCH /deliveries/{id}
//   - CandidateChips     음성 초안이 확정 못 한 품목·장소의 후보 버튼
// 새 예약에는 '말로 예약'(VoiceDraftBar, 2026-10-26)이 붙는다 — 초안으로 목적지·품목 줄을 채울 뿐, 예약은 '예약'을 눌러야 한다.
// 음성으로 채운 줄의 비품이 약품이면 '확인함'을 표시해야 예약할 수 있다(사용자 결정: 약품은 자동 확정하지 않음)
// 여러 병동 (2026-10-30, 사용자 "한번에 여러 병동을 배송"): 새 신청에 '+ 병동 추가' — 병동마다 신청 1건, 보낼 시간은 같다.
// 재고는 모든 병동 합계로 확인한다. 음성 초안은 마지막 병동을 채운다. 변경은 신청 1건(병동 1곳)만
// =============================================================================
import { useEffect, useState } from 'react'
import { useDeliveryMutations, useLocations, useSupplies } from '../../api/hooks'
import type { Delivery, DeliveryCreate, DeliveryWard, VoiceCandidate, VoiceDraft } from '../../api/types'
import { Button, Input, Label, Select } from '../../components/ui'
import { VoiceDraftBar } from '../voice/VoiceDraftBar'

interface ItemRow {
  supply_id: number | ''
  quantity: number
  voice?: { spokenName: string; candidates: VoiceCandidate[] }   // 음성 초안으로 채운 줄
  checked?: boolean                                              // 음성으로 채운 약품 줄을 간호사가 확인함
}

const EMPTY_ROW: ItemRow = { supply_id: '', quantity: 1 }

interface WardRow {
  destination: number | ''
  locationCandidates: VoiceCandidate[]   // 음성 초안이 확정 못 한 장소 후보
  items: ItemRow[]
}

const emptyWard = (): WardRow => ({ destination: '', locationCandidates: [], items: [EMPTY_ROW] })

/** 확정 못 한 품목·장소의 후보. [입력] candidates / onPick(id) [출력] 버튼 줄 */
function CandidateChips({ candidates, onPick }: { candidates: VoiceCandidate[]; onPick: (id: number) => void }) {
  if (candidates.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs">
      <span className="text-slate-500">후보:</span>
      {candidates.map(candidate => (
        <button key={candidate.id} type="button" onClick={() => onPick(candidate.id)}
          className="rounded border border-blue-200 bg-white px-2 py-0.5 text-blue-700 hover:bg-blue-50">
          {candidate.name}
        </button>
      ))}
    </div>
  )
}

/** datetime-local 값 → ISO 8601 (타임존 포함). 백엔드는 aware datetime만 받는다. */
const toIso = (local: string) => new Date(local).toISOString()

/** Date → datetime-local 형식(초 없음, 로컬 시간대) */
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 기본 예약 시각: 지금 + 10분 */
function defaultScheduled(): string {
  const d = new Date(Date.now() + 10 * 60_000)
  d.setSeconds(0, 0)
  return toLocalInput(d)
}

/** 현재 시각(ms). 렌더는 순수해야 하므로 상태로 두고 refreshIntervalMs마다 갱신한다. */
function useNow(refreshIntervalMs: number): number {
  const [nowMs, setNowMs] = useState(Date.now)
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), refreshIntervalMs)
    return () => clearInterval(timer)
  }, [refreshIntervalMs])
  return nowMs
}

interface Props {
  initial?: Delivery   // 있으면 변경 모드
  onDone?: () => void
}

export function DeliveryForm({ initial, onDone }: Props) {
  const locations = useLocations()
  const supplies = useSupplies()
  const { create, createMulti, update } = useDeliveryMutations()
  const isPending = create.isPending || createMulti.isPending || update.isPending
  const nowMs = useNow(30_000)

  const [scheduled, setScheduled] = useState(initial ? toLocalInput(new Date(initial.scheduled_at)) : defaultScheduled)
  const [wards, setWards] = useState<WardRow[]>(() => initial
    ? [{
        destination: initial.destination_location_id,
        locationCandidates: [],
        items: initial.items.map(i => ({ supply_id: i.supply_id, quantity: i.quantity })),
      }]
    : [emptyWard()])

  const setWard = (wardIndex: number, patch: Partial<WardRow>) =>
    setWards(rows => rows.map((ward, idx) => (idx === wardIndex ? { ...ward, ...patch } : ward)))
  const setItems = (wardIndex: number, change: (rows: ItemRow[]) => ItemRow[]) =>
    setWards(rows => rows.map((ward, idx) => (idx === wardIndex ? { ...ward, items: change(ward.items) } : ward)))
  const setItem = (wardIndex: number, i: number, patch: Partial<ItemRow>) =>
    setItems(wardIndex, rows => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))

  // 예약할 수 있는 수량 = 지금 재고 + (변경 중이면) 이 예약이 이미 잡아 둔 수량. 재고는 예약 때 이미 빠져 있다
  const stockBySupplyId = new Map((supplies.data ?? []).map(supply => [supply.id, supply.stock_qty]))
  const reservedByThisDelivery = new Map((initial?.items ?? []).map(item => [item.supply_id, item.quantity]))
  const availableQuantity = (supplyId: number) =>
    (stockBySupplyId.get(supplyId) ?? 0) + (reservedByThisDelivery.get(supplyId) ?? 0)
  // 같은 비품을 여러 병동에 보내면 합계로 본다 (백엔드도 합계로 확인)
  const requestedBySupplyId = new Map<number, number>()
  for (const row of wards.flatMap(ward => ward.items)) {
    if (row.supply_id !== '') requestedBySupplyId.set(row.supply_id, (requestedBySupplyId.get(row.supply_id) ?? 0) + row.quantity)
  }
  const exceedsStock = (row: ItemRow) =>
    row.supply_id !== '' && (requestedBySupplyId.get(row.supply_id) ?? 0) > availableQuantity(row.supply_id)
  const medicationIds = new Set((supplies.data ?? []).filter(supply => supply.category === 'medication').map(supply => supply.id))
  const needsCheck = (row: ItemRow) => row.voice !== undefined && row.supply_id !== '' && medicationIds.has(row.supply_id)

  /** 음성 초안 → 마지막 병동의 목적지·품목 줄. 예약 시각은 그대로 둔다. [입력] draft [출력] 없음 */
  const applyDraft = (draft: VoiceDraft) => {
    setWard(wards.length - 1, {
      destination: draft.location.location_id ?? '',
      locationCandidates: draft.location.location_id === null ? draft.location.candidates : [],
      items: draft.items.length === 0 ? [EMPTY_ROW] : draft.items.map(item => ({
        supply_id: item.supply_id ?? '',
        quantity: item.quantity,
        voice: { spokenName: item.spoken_name, candidates: item.candidates },
        checked: false,
      })),
    })
  }

  // 백엔드 규칙과 동일: 미래 시각, 병동마다 목적지·품목 1개 이상·같은 비품은 한 줄, 같은 병동은 한 번, 재고 합계 이하
  const isFuture = scheduled !== '' && new Date(scheduled).getTime() > nowMs
  const chosenDestinations = wards.map(ward => ward.destination).filter(destination => destination !== '')
  const hasDuplicateWard = new Set(chosenDestinations).size !== chosenDestinations.length
  const wardValid = (ward: WardRow) =>
    ward.destination !== '' &&
    ward.items.length > 0 &&
    ward.items.every(r => r.supply_id !== '' && r.quantity > 0 && !exceedsStock(r) && (!needsCheck(r) || r.checked)) &&
    new Set(ward.items.map(r => r.supply_id)).size === ward.items.length
  const valid = isFuture && !hasDuplicateWard && wards.every(wardValid)

  const toWard = (ward: WardRow): DeliveryWard => ({
    destination_location_id: Number(ward.destination),
    items: ward.items.map(r => ({ supply_id: Number(r.supply_id), quantity: r.quantity })),
  })

  const submit = () => {
    if (!valid) return
    const done = () => { if (!initial) setWards([emptyWard()]); onDone?.() }
    if (wards.length > 1) {
      createMulti.mutate({ scheduled_at: toIso(scheduled), destinations: wards.map(toWard) }, { onSuccess: done })
      return
    }
    const [onlyWard] = wards
    if (!onlyWard) return
    const body: DeliveryCreate = { ...toWard(onlyWard), scheduled_at: toIso(scheduled) }
    if (initial) update.mutate({ id: initial.id, body }, { onSuccess: done })
    else create.mutate(body, { onSuccess: done })
  }

  const locOptions = (locations.data ?? []).map(l => ({
    id: l.id,
    label: l.map_x_m == null ? `${l.name} (좌표 없음)` : l.name,
  }))

  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
      <h2 className="font-medium">{initial ? `신청 NO ${initial.id} 변경` : '새 물품 신청'}</h2>
      {!initial && <VoiceDraftBar onDraft={applyDraft} />}
      <Label text="보낼 시간">
        <Input type="datetime-local" value={scheduled} onChange={e => setScheduled(e.target.value)} />
      </Label>
      {scheduled !== '' && !isFuture && <p className="text-xs text-red-600">보낼 시간은 지금보다 뒤여야 합니다</p>}

      {wards.map((ward, wardIndex) => (
        <div key={wardIndex} className={wards.length > 1 ? 'space-y-3 rounded border border-slate-200 p-3' : 'space-y-3'}>
          {wards.length > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700">병동 {wardIndex + 1}</span>
              <Button variant="secondary" onClick={() => setWards(rows => rows.filter((_, idx) => idx !== wardIndex))}>
                병동 빼기
              </Button>
            </div>
          )}
          <Label text="목적지">
            <Select value={ward.destination} onChange={e => setWard(wardIndex, { destination: e.target.value === '' ? '' : Number(e.target.value) })}>
              <option value="">선택</option>
              {locOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
            </Select>
            {ward.destination === '' && (
              <CandidateChips candidates={ward.locationCandidates} onPick={locationId => setWard(wardIndex, { destination: locationId })} />
            )}
          </Label>
          {ward.destination !== '' && wards.some((other, idx) => idx !== wardIndex && other.destination === ward.destination) && (
            <p className="text-xs text-red-600">같은 병동이 두 번 들어 있습니다. 한 병동으로 합쳐 주세요</p>
          )}

          <div className="space-y-2">
            <span className="text-sm text-slate-600">품목</span>
            {ward.items.map((row, i) => (
              <div key={i} className="space-y-1">
                <div className="flex gap-2">
                  <Select value={row.supply_id} onChange={e => setItem(wardIndex, i, { supply_id: e.target.value === '' ? '' : Number(e.target.value), checked: false })}>
                    <option value="">비품 선택</option>
                    {(supplies.data ?? []).map(s => (
                      <option key={s.id} value={s.id}>{s.code} · {s.name} (신청 가능 {availableQuantity(s.id)})</option>
                    ))}
                  </Select>
                  <div className="w-24">
                    <Input type="number" min={1} value={row.quantity}
                      onChange={e => setItem(wardIndex, i, { quantity: Math.max(1, Number(e.target.value)) })} />
                  </div>
                  <Button variant="secondary" onClick={() => setItems(wardIndex, rows => rows.filter((_, idx) => idx !== i))} disabled={ward.items.length === 1}>
                    삭제
                  </Button>
                </div>
                {row.voice && (
                  <p className="text-xs text-slate-500">들은 말: “{row.voice.spokenName}”</p>
                )}
                {row.voice && row.supply_id === '' && (
                  <CandidateChips candidates={row.voice.candidates} onPick={supplyId => setItem(wardIndex, i, { supply_id: supplyId, checked: false })} />
                )}
                {needsCheck(row) && (
                  <label className="flex items-center gap-2 rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
                    <input type="checkbox" checked={row.checked ?? false} onChange={e => setItem(wardIndex, i, { checked: e.target.checked })} />
                    약품입니다 — 품목·수량을 확인했습니다 (확인해야 예약할 수 있습니다)
                  </label>
                )}
                {row.supply_id !== '' && exceedsStock(row) && (
                  <p className="text-xs text-amber-700">
                    신청 가능한 수량({availableQuantity(row.supply_id)}개)보다 많습니다{wards.length > 1 ? ' — 모든 병동 합계' : ''}
                  </p>
                )}
              </div>
            ))}
            <Button variant="secondary" onClick={() => setItems(wardIndex, rows => [...rows, EMPTY_ROW])}>
              + 품목 추가
            </Button>
          </div>
        </div>
      ))}
      {!initial && (
        <Button variant="secondary" onClick={() => setWards(rows => [...rows, emptyWard()])}>
          + 병동 추가
        </Button>
      )}

      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={!valid || isPending}>
          {isPending ? '저장 중…' : initial ? '변경 저장' : wards.length > 1 ? `${wards.length}개 병동 신청` : '신청'}
        </Button>
        {initial && <Button variant="secondary" onClick={onDone}>취소</Button>}
      </div>
    </div>
  )
}
