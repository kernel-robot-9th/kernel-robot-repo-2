// =============================================================================
// 파일   : src/features/deliveries/DeliveryForm.tsx
// 역할   : 배송 예약 생성·변경 폼 — 목적지·예약 시각(미래)·품목(비품+수량, 예약 가능 수량 이하) 여러 줄
// 작성일 : 2026-10-14
// 구성   :
//   - ItemRow            품목 한 줄 상태
//   - toLocalInput/toIso datetime-local ↔ ISO 변환
//   - useNow             현재 시각 상태 (렌더 중 Date.now() 호출 대신)
//   - DeliveryForm       initial 없으면 POST /deliveries, 있으면 PATCH /deliveries/{id}
// =============================================================================
import { useEffect, useState } from 'react'
import { useDeliveryMutations, useLocations, useSupplies } from '../../api/hooks'
import type { Delivery, DeliveryCreate } from '../../api/types'
import { Button, Input, Label, Select } from '../../components/ui'

interface ItemRow {
  supply_id: number | ''
  quantity: number
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
  const { create, update } = useDeliveryMutations()
  const mutation = initial ? update : create
  const nowMs = useNow(30_000)

  const [destination, setDestination] = useState<number | ''>(initial?.destination_location_id ?? '')
  const [scheduled, setScheduled] = useState(initial ? toLocalInput(new Date(initial.scheduled_at)) : defaultScheduled)
  const [items, setItems] = useState<ItemRow[]>(
    initial?.items.map(i => ({ supply_id: i.supply_id, quantity: i.quantity })) ?? [{ supply_id: '', quantity: 1 }],
  )

  const setItem = (i: number, patch: Partial<ItemRow>) =>
    setItems(rows => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))

  // 예약할 수 있는 수량 = 지금 재고 + (변경 중이면) 이 예약이 이미 잡아 둔 수량. 재고는 예약 때 이미 빠져 있다
  const stockBySupplyId = new Map((supplies.data ?? []).map(supply => [supply.id, supply.stock_qty]))
  const reservedByThisDelivery = new Map((initial?.items ?? []).map(item => [item.supply_id, item.quantity]))
  const availableQuantity = (supplyId: number) =>
    (stockBySupplyId.get(supplyId) ?? 0) + (reservedByThisDelivery.get(supplyId) ?? 0)
  const exceedsStock = (row: ItemRow) => row.supply_id !== '' && row.quantity > availableQuantity(row.supply_id)

  // 백엔드 규칙과 동일: 미래 시각, 품목 1개 이상, 같은 비품은 한 줄, 재고 이하
  const isFuture = scheduled !== '' && new Date(scheduled).getTime() > nowMs
  const valid =
    destination !== '' &&
    isFuture &&
    items.length > 0 &&
    items.every(r => r.supply_id !== '' && r.quantity > 0 && !exceedsStock(r)) &&
    new Set(items.map(r => r.supply_id)).size === items.length

  const submit = () => {
    if (!valid) return
    const body: DeliveryCreate = {
      destination_location_id: Number(destination),
      scheduled_at: toIso(scheduled),
      items: items.map(r => ({ supply_id: Number(r.supply_id), quantity: r.quantity })),
    }
    const done = () => { if (!initial) setItems([{ supply_id: '', quantity: 1 }]); onDone?.() }
    if (initial) update.mutate({ id: initial.id, body }, { onSuccess: done })
    else create.mutate(body, { onSuccess: done })
  }

  const locOptions = (locations.data ?? []).map(l => ({
    id: l.id,
    label: l.map_x_m == null ? `${l.name} (좌표 없음)` : l.name,
  }))

  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
      <h2 className="font-medium">{initial ? `예약 #${initial.id} 변경` : '새 배송 예약'}</h2>
      <div className="grid grid-cols-2 gap-3">
        <Label text="목적지">
          <Select value={destination} onChange={e => setDestination(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">선택</option>
            {locOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
          </Select>
        </Label>
        <Label text="예약 시각 (미래)">
          <Input type="datetime-local" value={scheduled} onChange={e => setScheduled(e.target.value)} />
        </Label>
      </div>
      {scheduled !== '' && !isFuture && <p className="text-xs text-red-600">예약 시각은 지금보다 뒤여야 합니다</p>}

      <div className="space-y-2">
        <span className="text-sm text-slate-600">품목</span>
        {items.map((row, i) => (
          <div key={i} className="space-y-1">
            <div className="flex gap-2">
              <Select value={row.supply_id} onChange={e => setItem(i, { supply_id: e.target.value === '' ? '' : Number(e.target.value) })}>
                <option value="">비품 선택</option>
                {(supplies.data ?? []).map(s => (
                  <option key={s.id} value={s.id}>{s.code} · {s.name} (예약 가능 {availableQuantity(s.id)})</option>
                ))}
              </Select>
              <div className="w-24">
                <Input type="number" min={1} value={row.quantity}
                  onChange={e => setItem(i, { quantity: Math.max(1, Number(e.target.value)) })} />
              </div>
              <Button variant="secondary" onClick={() => setItems(rows => rows.filter((_, idx) => idx !== i))} disabled={items.length === 1}>
                삭제
              </Button>
            </div>
            {row.supply_id !== '' && exceedsStock(row) && (
              <p className="text-xs text-amber-700">예약 가능한 수량({availableQuantity(row.supply_id)}개)보다 많습니다</p>
            )}
          </div>
        ))}
        <Button variant="secondary" onClick={() => setItems(rows => [...rows, { supply_id: '', quantity: 1 }])}>
          + 품목 추가
        </Button>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={!valid || mutation.isPending}>
          {mutation.isPending ? '저장 중…' : initial ? '변경 저장' : '예약'}
        </Button>
        {initial && <Button variant="secondary" onClick={onDone}>취소</Button>}
      </div>
    </div>
  )
}
