// =============================================================================
// 파일   : src/pages/Deliveries.tsx
// 역할   : 본인 배송 예약 목록 + 생성 + 변경(reserved만) + 취소(reserved만) + 배송 단계 + 일회용 수령 마커
// 작성일 : 2026-10-14
// 구성   :
//   - Deliveries   목록 테이블. 장소·비품 id를 이름으로 치환. 로봇이 상태를 바꾸므로 다시 불러온다
//                  (진행 중 5초·평소 30초 — hooks.ts). 도착한 배송은 '받았습니다'로 수령(2026-10-22 기본),
//                  마커 방식(receipt_method=marker)이면 '수령 마커'로 일회용 마커 창을 다시 연다 (2026-10-20)
//                  창 자체는 Layout의 ReceiptMarkerWatcher가 띄운다(도착하면 어느 화면에서든 자동)
//                  행마다 '기록'으로 그 배송의 예약·변경·취소·출발·도착·수령·실패 기록 창 (2026-10-21)
// =============================================================================
import { useMemo, useState } from 'react'
import { useDeliveries, useDeliveryMutations, useLocations, useSupplies } from '../api/hooks'
import { Button, LoadError, PageTitle, Table, Td, Th } from '../components/ui'
import { DeliveryForm } from '../features/deliveries/DeliveryForm'
import { DeliveryHistoryDialog } from '../features/deliveries/DeliveryHistoryDialog'
import { DeliveryProgress } from '../features/deliveries/DeliveryProgress'
import { openReceiptMarker } from '../features/deliveries/receiptMarkerStore'
import { formatDateTime } from '../lib/dateFormat'

export function Deliveries() {
  const deliveries = useDeliveries()
  const locations = useLocations()
  const supplies = useSupplies()
  const { cancel, confirmReceipt } = useDeliveryMutations()
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [historyId, setHistoryId] = useState<number | null>(null)   // '자세히' 창 — 등록한 시각도 여기서 보인다 (2026-10-27)

  const locName = useMemo(() => new Map((locations.data ?? []).map(l => [l.id, l.name])), [locations.data])
  const supName = useMemo(() => new Map((supplies.data ?? []).map(s => [s.id, s.name])), [supplies.data])

  const rows = [...(deliveries.data ?? [])].sort((a, b) => b.scheduled_at.localeCompare(a.scheduled_at))
  // 다시 불러온 목록에서 예약됨이 아니면(취소·수령됨) 변경 폼을 닫는다
  const editing = rows.find(d => d.id === editId && d.status === 'reserved')

  const cancelDelivery = (deliveryId: number) => {
    if (!confirm(`NO ${deliveryId} 신청을 취소할까요?`)) return
    if (deliveryId === editId) setEditId(null)
    cancel.mutate(deliveryId)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <PageTitle>물품 신청</PageTitle>
        <Button onClick={() => { setEditId(null); setShowForm(v => !v) }}>{showForm ? '닫기' : '+ 요청하기'}</Button>
      </div>

      {showForm && !editing && <DeliveryForm onDone={() => setShowForm(false)} />}
      {editing && <DeliveryForm key={editing.id} initial={editing} onDone={() => setEditId(null)} />}

      {deliveries.isError ? (
        <LoadError what="물품 신청 목록" error={deliveries.error} onRetry={() => void deliveries.refetch()} />
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>NO</Th><Th>보낼 시간</Th><Th>목적지</Th><Th>품목</Th><Th>배송 단계</Th><Th className="w-56">{' '}</Th>
            </tr>
          </thead>
          <tbody>
            {deliveries.isPending && <tr><td colSpan={6} className="px-3 py-2 text-slate-500">불러오는 중…</td></tr>}
            {rows.map(d => (
              <tr key={d.id} className={d.id === editing?.id ? 'bg-blue-50' : ''}>
                <Td>{d.id}</Td>
                <Td>{formatDateTime(d.scheduled_at)}</Td>
                <Td>{locName.get(d.destination_location_id) ?? `#${d.destination_location_id}`}</Td>
                <Td>{d.items.map(it => `${supName.get(it.supply_id) ?? `#${it.supply_id}`} ×${it.quantity}`).join(', ')}</Td>
                <Td><DeliveryProgress delivery={d} /></Td>
                {/* 작업 칸: 고정 폭으로 오른쪽 끝에 붙인다 — 버튼이 몇 개든 '자세히'가 같은 자리 (2026-10-27) */}
                <Td className="w-56">
                  <div className="flex justify-end gap-1">
                    {d.status === 'reserved' && (
                      <>
                        <Button variant="secondary" onClick={() => { setShowForm(false); setEditId(d.id) }}>변경</Button>
                        <Button variant="danger" onClick={() => cancelDelivery(d.id)} disabled={cancel.isPending}>취소</Button>
                      </>
                    )}
                    {d.status === 'arrived' && d.receipt_method === 'button' && (
                      <Button onClick={() => confirmReceipt.mutate(d.id)} disabled={confirmReceipt.isPending}>받았습니다</Button>
                    )}
                    {d.status === 'arrived' && d.receipt_method === 'marker' && d.receipt_marker_id != null && (
                      <Button onClick={() => openReceiptMarker(d.id)}>수령 마커</Button>
                    )}
                    <Button variant="secondary" onClick={() => setHistoryId(d.id)}>자세히</Button>
                  </div>
                </Td>
              </tr>
            ))}
            {!deliveries.isPending && rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-2 text-slate-500">신청한 물품이 없습니다</td></tr>
            )}
          </tbody>
        </Table>
      )}

      {historyId != null && (
        <DeliveryHistoryDialog deliveryId={historyId} onClose={() => setHistoryId(null)}
          registeredAt={(deliveries.data ?? []).find(delivery => delivery.id === historyId)?.created_at} />
      )}
    </div>
  )
}
