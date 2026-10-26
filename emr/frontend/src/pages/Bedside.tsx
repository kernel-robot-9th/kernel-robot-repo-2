// =============================================================================
// 파일   : src/pages/Bedside.tsx
// 역할   : 병상 화면 (/bedside) — 환자가 비품을 요청(SR-02)하고, 로봇이 도착하면 "받았습니다"(SR-06)를 누른다 (2026-10-22)
// 작성일 : 2026-10-22
// 구성   :
//   - Bedside        키 확인 → 요청 화면 또는 진행 화면. 간호사 로그인과 별개(Layout 밖, X-Bedside-Api-Key)
//   - KeyEntry       관리자에게 받은 병상 단말 키 입력 (태블릿 브라우저에 저장)
//   - RequestPanel   환자용 품목(requestable_by = patient)과 수량 1–5 → 요청하기 (간호사 승인 없이 바로 로봇이 가져감)
//   - ProgressPanel  요청됨 → 출발 → 도착 → 받음. 도착하면 큰 "받았습니다" 버튼
// 병상당 진행 중 1건(서버 409 bedside_request_in_progress). 일회용 마커·간호사 정보는 보여 주지 않는다.
// =============================================================================
import { useState } from 'react'
import { bedsideKey, isBedsideKeyError } from '../api/client'
import { describeError } from '../api/errorMessages'
import { useBedsideDeliveries, useBedsideMe, useBedsideMutations, useBedsideSupplies } from '../api/hooks'
import type { BedsideDelivery, BedsideSupply } from '../api/types'
import { BEDSIDE_MAX_QUANTITY, DELIVERY_FAILURE_REASON_LABEL } from '../api/types'
import { Button, Input } from '../components/ui'
import { useNowMs } from '../features/deliveries/useNowMs'
import { formatHourMinute } from '../lib/dateFormat'
const RECENT_RESULT_MS = 10 * 60_000   // 끝난 요청의 결과(받음·실패)를 이 시간 동안 보여 준다

function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  const description = describeError(error)
  return (
    <div role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-red-800">
      <p className="font-medium">{description.message}</p>
      {description.hint && <p className="text-sm">{description.hint}</p>}
    </div>
  )
}

// ---------- 키 입력 ----------
function KeyEntry({ onSaved, reason }: { onSaved: () => void; reason?: string }) {
  const [value, setValue] = useState('')
  return (
    <div className="mx-auto max-w-md space-y-4 rounded-xl bg-white p-6 shadow-sm">
      <h1 className="text-xl font-bold">병상 화면 설정</h1>
      <p className="text-slate-600">관리자에게 받은 <b>병상 단말 키</b>를 입력해 주세요. 이 태블릿에 저장됩니다.</p>
      {reason && <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-900">{reason}</p>}
      <label className="block space-y-1">
        <span className="text-sm text-slate-600">병상 단말 키</span>
        <Input id="bedside-key" value={value} onChange={e => setValue(e.target.value)} placeholder="emr_bk_..." autoComplete="off" />
      </label>
      <Button className="w-full py-3 text-base" disabled={!value.trim()} onClick={() => { bedsideKey.set(value.trim()); onSaved() }}>
        저장하고 시작
      </Button>
    </div>
  )
}

// ---------- 요청 ----------
function RequestPanel({ supplies, roomReady }: { supplies: BedsideSupply[]; roomReady: boolean }) {
  const { request } = useBedsideMutations()
  const [quantities, setQuantities] = useState<Record<number, number>>({})
  const chosen = Object.entries(quantities).filter(([, quantity]) => quantity > 0)
  const change = (supplyId: number, delta: number) =>
    setQuantities(previous => ({ ...previous, [supplyId]: Math.min(BEDSIDE_MAX_QUANTITY, Math.max(0, (previous[supplyId] ?? 0) + delta)) }))
  const submit = () => request.mutate(
    { items: chosen.map(([supplyId, quantity]) => ({ supply_id: Number(supplyId), quantity })) },
    { onSuccess: () => setQuantities({}) },
  )

  return (
    <section className="space-y-4" aria-label="비품 요청">
      <h2 className="text-lg font-semibold">필요한 물품을 골라 주세요</h2>
      {!roomReady && (
        <p className="rounded-lg bg-amber-50 px-4 py-3 text-amber-900">이 병실은 아직 로봇이 갈 수 없습니다. 간호사에게 말씀해 주세요.</p>
      )}
      <ul className="grid gap-3 sm:grid-cols-2">
        {supplies.map(supply => {
          const quantity = quantities[supply.id] ?? 0
          return (
            <li key={supply.id} className={`flex items-center justify-between gap-3 rounded-xl border bg-white p-4 ${quantity > 0 ? 'border-blue-500 ring-2 ring-blue-100' : 'border-slate-200'}`}>
              <div>
                <p className="text-lg font-medium">{supply.name}</p>
                {!supply.in_stock && <p className="text-sm text-slate-500">지금 재고가 없습니다</p>}
              </div>
              <div className="flex items-center gap-2">
                <button type="button" aria-label={`${supply.name} 하나 빼기`} disabled={quantity === 0}
                  className="h-11 w-11 rounded-full border border-slate-300 text-xl disabled:opacity-30" onClick={() => change(supply.id, -1)}>−</button>
                <span className="w-6 text-center text-xl tabular-nums" aria-live="polite">{quantity}</span>
                <button type="button" aria-label={`${supply.name} 하나 더`} disabled={!supply.in_stock || quantity >= BEDSIDE_MAX_QUANTITY}
                  className="h-11 w-11 rounded-full border border-slate-300 text-xl disabled:opacity-30" onClick={() => change(supply.id, 1)}>+</button>
              </div>
            </li>
          )
        })}
        {supplies.length === 0 && <li className="text-slate-500">요청할 수 있는 물품이 없습니다.</li>}
      </ul>
      <p className="text-sm text-slate-500">한 물품은 {BEDSIDE_MAX_QUANTITY}개까지 요청할 수 있습니다. 요청하면 로봇이 바로 가져다 드립니다.</p>
      <ErrorNote error={request.error} />
      <Button className="w-full py-4 text-lg" disabled={!chosen.length || !roomReady || request.isPending} onClick={submit}>
        {request.isPending ? '요청하는 중…' : `요청하기${chosen.length ? ` (${chosen.length}가지)` : ''}`}
      </Button>
    </section>
  )
}

// ---------- 진행 ----------
const STEPS: [BedsideDelivery['status'], string][] = [['reserved', '요청됨'], ['dispatched', '출발'], ['arrived', '도착'], ['received', '받음']]

function ProgressPanel({ delivery }: { delivery: BedsideDelivery }) {
  const { confirmReceipt } = useBedsideMutations()
  const reached = STEPS.findIndex(([status]) => status === delivery.status)
  const items = delivery.items.map(item => `${item.name} ${item.quantity}개`).join(', ')
  const message = {
    reserved: '요청을 받았습니다. 로봇이 곧 출발합니다.',
    dispatched: `${delivery.assigned_robot_name ?? '로봇'}이(가) 출발했습니다 (${formatHourMinute(delivery.dispatched_at)}).`,
    arrived: '로봇이 도착했습니다. 물건을 받으신 뒤 아래 버튼을 눌러 주세요.',
    received: '받으셨습니다. 감사합니다.',
    failed: `배송하지 못했습니다: ${delivery.failure_reason ? DELIVERY_FAILURE_REASON_LABEL[delivery.failure_reason] : ''}. 간호사에게 말씀해 주세요.`,
    cancelled: '취소되었습니다.',
  }[delivery.status]

  return (
    <section className="space-y-5 rounded-xl bg-white p-6 shadow-sm" aria-label="요청 진행">
      <p className="text-slate-600">{items}</p>
      <ol className="flex gap-2" aria-label="진행 단계">
        {STEPS.map(([status, label], index) => {
          const done = delivery.status !== 'failed' && index <= reached
          return (
            <li key={status} aria-current={index === reached ? 'step' : undefined}
              className={`flex-1 rounded-full py-2 text-center text-sm font-medium ${done ? (index === reached ? 'bg-blue-600 text-white' : 'bg-blue-100 text-blue-800') : 'bg-slate-100 text-slate-500'}`}>
              {label}
            </li>
          )
        })}
      </ol>
      <p className={`text-lg ${delivery.status === 'failed' ? 'text-red-700' : ''}`} aria-live="polite">{message}</p>
      {delivery.status === 'arrived' && (
        <>
          <ErrorNote error={confirmReceipt.error} />
          <button type="button" disabled={confirmReceipt.isPending} onClick={() => confirmReceipt.mutate(delivery.id)}
            className="w-full rounded-xl bg-green-600 py-6 text-2xl font-bold text-white shadow hover:bg-green-700 disabled:opacity-50">
            받았습니다
          </button>
          {delivery.receipt_deadline_at && (
            <p className="text-center text-sm text-slate-500">{formatHourMinute(delivery.receipt_deadline_at)}까지 누르지 않으면 로봇이 돌아갑니다.</p>
          )}
        </>
      )}
    </section>
  )
}

// ---------- 화면 ----------
export function Bedside() {
  const [hasKey, setHasKey] = useState(() => bedsideKey.get() !== null)
  const me = useBedsideMe(hasKey)
  const supplies = useBedsideSupplies(hasKey)
  const deliveries = useBedsideDeliveries(hasKey)
  const keyRejected = me.isError && isBedsideKeyError(me.error)
  const nowMs = useNowMs(15_000)

  let body
  if (!hasKey || keyRejected) {
    body = <KeyEntry reason={keyRejected ? '키가 틀렸거나 폐기되었습니다. 새 키를 입력해 주세요.' : undefined}
      onSaved={() => { setHasKey(true); void me.refetch(); void supplies.refetch(); void deliveries.refetch() }} />
  } else if (me.isPending) {
    body = <p className="text-center text-slate-500">불러오는 중…</p>
  } else if (me.isError) {
    body = <ErrorNote error={me.error} />
  } else {
    const active = me.data.active_delivery
    const latest = deliveries.data?.[0]
    const recentResult = !active && latest && (latest.status === 'received' || latest.status === 'failed')
      && Date.parse(latest.received_at ?? latest.failed_at ?? '') > nowMs - RECENT_RESULT_MS ? latest : null
    body = (
      <div className="space-y-6">
        <header>
          <p className="text-sm text-slate-500">병상</p>
          <h1 className="text-2xl font-bold">{me.data.name} <span className="text-lg font-normal text-slate-500">· {me.data.room.name}</span></h1>
        </header>
        {active ? <ProgressPanel delivery={active} /> : (
          <>
            {recentResult && <ProgressPanel delivery={recentResult} />}
            <RequestPanel supplies={supplies.data ?? []} roomReady={me.data.room.has_position} />
          </>
        )}
        <button type="button" className="text-xs text-slate-400 underline"
          onClick={() => { if (confirm('이 태블릿의 병상 단말 키를 지울까요?')) { bedsideKey.clear(); setHasKey(false) } }}>
          단말 키 바꾸기
        </button>
      </div>
    )
  }

  return <main className="min-h-screen bg-slate-50 px-4 py-8"><div className="mx-auto max-w-2xl">{body}</div></main>
}
