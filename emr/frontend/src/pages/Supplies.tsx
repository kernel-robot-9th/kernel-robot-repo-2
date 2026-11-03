// =============================================================================
// 파일   : src/pages/Supplies.tsx
// 역할   : 비품 목록 + 등록 + 인라인 편집(재고·부족 알림 기준) + 삭제(표시만)
//          유효기간은 고르지 않는다 — 등록하면 서버가 오늘부터 6개월~1년 사이로 정하고, 목록에는 보여 주기만 한다 (2026-10-19)
//          재고(stock_qty)는 예약 가능 수량 — 배송 예약 시 차감, 취소 시 복구 (2026-10-15 결정)
//          재고가 알림 기준 이하면 행을 붉게 표시하고, 모든 간호사 화면에 실시간 알림 (2026-10-16)
// 작성일 : 2026-10-14
// 구성   :
//   - SupplyCreateForm   POST /supplies
//   - Supplies           테이블. 재고·알림 기준은 셀에서 바로 PATCH, 유효기간은 읽기 전용
// =============================================================================
import { useState } from 'react'
import { useSupplies, useSupplyMutations } from '../api/hooks'
import type { SupplyCategory, SupplyCreate, RequestableBy } from '../api/types'
import { Button, Input, Label, LoadError, PageTitle, Select, Table, Td, Th } from '../components/ui'

const CATEGORY_LABEL: Record<SupplyCategory, string> = { medication: '약품', supply: '비품' }
const REQ_LABEL: Record<RequestableBy, string> = { nurse: '간호사', patient: '환자(병상)' }

/** 목적격 조사 — 마지막 글자에 받침이 있으면 '을', 없으면 '를'. [입력] word [출력] '을' | '를' */
function objectParticle(word: string): string {
  const code = word.charCodeAt(word.length - 1) - 0xac00
  return code >= 0 && code <= 11171 && code % 28 !== 0 ? '을' : '를'
}

function SupplyCreateForm({ onDone }: { onDone: () => void }) {
  const { create } = useSupplyMutations()
  const [form, setForm] = useState<SupplyCreate>({
    code: '', name: '', category: 'supply', requestable_by: 'nurse', stock_qty: 0, low_stock_threshold_qty: null, expiry_date: null,
  })
  const set = <K extends keyof SupplyCreate>(k: K, v: SupplyCreate[K]) => setForm(f => ({ ...f, [k]: v }))

  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
      <div className="grid grid-cols-3 gap-3">
        <Label text="코드"><Input value={form.code} onChange={e => set('code', e.target.value)} placeholder="MED-001" /></Label>
        <Label text="이름"><Input value={form.name} onChange={e => set('name', e.target.value)} /></Label>
        <Label text="분류">
          <Select value={form.category} onChange={e => set('category', e.target.value as SupplyCategory)}>
            <option value="supply">비품</option><option value="medication">약품</option>
          </Select>
        </Label>
        <Label text="요청 가능">
          <Select value={form.requestable_by} onChange={e => set('requestable_by', e.target.value as RequestableBy)}>
            <option value="nurse">간호사</option><option value="patient">환자(병상)</option>
          </Select>
        </Label>
        <Label text="재고"><Input type="number" min={0} value={form.stock_qty} onChange={e => set('stock_qty', Number(e.target.value))} /></Label>
        <Label text="이 수량 이하면 알림 (선택)">
          <Input type="number" min={0} placeholder="알림 안 함" value={form.low_stock_threshold_qty ?? ''}
            onChange={e => set('low_stock_threshold_qty', e.target.value === '' ? null : Number(e.target.value))} />
        </Label>
      </div>
      <div className="flex items-center gap-3">
        <Button disabled={!form.code || !form.name || create.isPending} onClick={() => create.mutate(form, { onSuccess: onDone })}>
          등록
        </Button>
      </div>
    </div>
  )
}

export function Supplies() {
  const supplies = useSupplies()
  const { update, remove } = useSupplyMutations()
  const [showForm, setShowForm] = useState(false)
  const [q, setQ] = useState('')

  const rows = (supplies.data ?? []).filter(s =>
    q === '' || s.code.toLowerCase().includes(q.toLowerCase()) || s.name.includes(q),
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <PageTitle>재고 관리</PageTitle>
        <div className="flex gap-2">
          <div className="w-64"><Input placeholder="물품 번호나 물품 이름으로 찾기" value={q} onChange={e => setQ(e.target.value)} /></div>
          <Button onClick={() => setShowForm(v => !v)}>{showForm ? '닫기' : '+ 물품 추가'}</Button>
        </div>
      </div>
      {showForm && <SupplyCreateForm onDone={() => setShowForm(false)} />}
      <p className="text-sm text-slate-500">남은 수량은 신청된 수량을 뺀 값입니다. 직접 세어 고칠 때도 신청된 수량을 빼고 입력해 주세요.</p>
      <p className="text-sm text-slate-500">기준 수량을 넣으면, 남은 수량이 그 이하일 때 모든 간호사에게 알림이 갑니다.</p>

      {supplies.isError ? (
        <LoadError what="비품 목록" error={supplies.error} onRetry={() => void supplies.refetch()} />
      ) : (
        <Table>
          <thead>
            <tr><Th>코드</Th><Th>이름</Th><Th>분류</Th><Th>요청 가능</Th><Th>재고 (신청 가능)</Th><Th>부족 알림 기준</Th><Th>유효기간</Th><Th>{' '}</Th></tr>
          </thead>
          <tbody>
            {rows.map(s => {
              const isLowStock = s.low_stock_threshold_qty !== null && s.stock_qty <= s.low_stock_threshold_qty
              return (
              <tr key={s.id} className={isLowStock ? 'bg-red-50' : undefined}>
                <Td className="font-mono">{s.code}</Td>
                <Td>{s.name}{isLowStock && <span className="ml-2 rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-700">부족</span>}
                  {isLowStock && <span className="block text-xs text-red-700">기준 수량보다 부족합니다. 수량을 확인해서 입력해 주세요.</span>}</Td>
                <Td>{CATEGORY_LABEL[s.category]}</Td>
                <Td>{REQ_LABEL[s.requestable_by]}</Td>
                <Td>
                  {/* 재고는 셀에서 바로 수정 — blur 시 PATCH. key: 예약·알림으로 서버 값이 바뀌면 입력칸도 새 값으로 */}
                  <Input
                    key={s.stock_qty} type="number" min={0} className="w-20" defaultValue={s.stock_qty}
                    onBlur={e => {
                      const v = Number(e.target.value)
                      if (v !== s.stock_qty) update.mutate({ id: s.id, body: { stock_qty: v } })
                    }}
                  />
                </Td>
                <Td>
                  <Input
                    key={s.low_stock_threshold_qty ?? 'none'} type="number" min={0} className="w-20" placeholder="없음"
                    aria-label={`${s.name} 부족 알림 기준`} defaultValue={s.low_stock_threshold_qty ?? ''}
                    onBlur={e => {
                      const v = e.target.value === '' ? null : Number(e.target.value)
                      if (v !== s.low_stock_threshold_qty) update.mutate({ id: s.id, body: { low_stock_threshold_qty: v } })
                    }}
                  />
                </Td>
                <Td className="whitespace-nowrap tabular-nums">{s.expiry_date ?? '—'}</Td>
                <Td>
                  <Button variant="danger" onClick={() => { if (confirm(`${s.name}${objectParticle(s.name)} 목록에서 뺄까요?`)) remove.mutate(s.id) }}>삭제</Button>
                </Td>
              </tr>
              )
            })}
            {!supplies.isPending && rows.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-2 text-slate-500">등록된 물품이 없습니다.</td></tr>
            )}
          </tbody>
        </Table>
      )}
    </div>
  )
}
