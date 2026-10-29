// =============================================================================
// 파일   : src/pages/DeliveryLog.tsx
// 역할   : 관리자 배송 기록 화면 — 모든 배송의 예약·변경·취소·출발·도착·수령·실패, 최근 것부터 (로드맵 4단계, 2026-10-21)
// 작성일 : 2026-10-21
// 구성   :
//   - DeliveryLog  거르기(사건·로봇·예약 간호사·배송 번호·기간) + 표 + 더 보기(50개씩)
// 관리자 메뉴에만 보이고, 실제 차단은 백엔드(403 admin_required)가 한다. 일회용 마커 번호는 기록에 없다
// =============================================================================
import { useState } from 'react'
import { useDeliveryEventLog, useIsAdmin, useMe, useNurses, useRobots } from '../api/hooks'
import type { DeliveryEventFilters, DeliveryEventType } from '../api/types'
import { DELIVERY_EVENT_LABEL } from '../api/types'
import { Badge, Button, Input, Label, LoadError, PageTitle, Select, Table, Td, Th } from '../components/ui'
import { describeEvent } from '../features/deliveries/deliveryEventText'
import { formatDateTimeSeconds } from '../lib/dateFormat'

const EVENT_TYPES = Object.keys(DELIVERY_EVENT_LABEL) as DeliveryEventType[]

/** 화면의 거르기 칸 (모두 문자열 — 빈 값은 거르지 않음) */
interface FilterForm {
  eventType: string
  robotId: string
  nurseId: string
  deliveryId: string
  fromDate: string   // YYYY-MM-DD, 그날 0시부터 (이 PC 시간대)
  toDate: string     // YYYY-MM-DD, 그날 끝까지
}
const EMPTY_FILTERS: FilterForm = { eventType: '', robotId: '', nurseId: '', deliveryId: '', fromDate: '', toDate: '' }

/** 날짜 칸 → API 조건. 끝 날짜는 다음 날 0시 미만으로 보낸다 */
function toApiFilters(form: FilterForm): DeliveryEventFilters {
  const localMidnight = (date: string, addDays = 0) => {
    const day = new Date(`${date}T00:00:00`)
    day.setDate(day.getDate() + addDays)
    return day.toISOString()
  }
  return {
    event_type: (form.eventType || undefined) as DeliveryEventType | undefined,
    robot_id: form.robotId ? Number(form.robotId) : undefined,
    nurse_id: form.nurseId ? Number(form.nurseId) : undefined,
    delivery_id: form.deliveryId ? Number(form.deliveryId) : undefined,
    since: form.fromDate ? localMidnight(form.fromDate) : undefined,
    until: form.toDate ? localMidnight(form.toDate, 1) : undefined,
  }
}

export function DeliveryLog() {
  const me = useMe()
  const isAdmin = useIsAdmin()
  const [form, setForm] = useState<FilterForm>(EMPTY_FILTERS)
  const log = useDeliveryEventLog(toApiFilters(form))
  const robots = useRobots()
  const nurses = useNurses()

  const set = (field: keyof FilterForm) => (event: { target: { value: string } }) =>
    setForm(previous => ({ ...previous, [field]: event.target.value }))
  const rows = log.data?.pages.flat() ?? []

  if (me.data && !isAdmin) {
    return (
      <div className="space-y-4">
        <PageTitle>배송 기록</PageTitle>
        <p className="text-sm text-slate-500">배송 기록 전체는 관리자만 볼 수 있습니다. 내 배송의 기록은 '물품 신청' 화면의 '기록'에서 봅니다.</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <PageTitle>배송 기록</PageTitle>
      <p className="text-sm text-slate-500">
        간호사 예약·변경·취소, 병상(환자) 요청·받았습니다, 로봇 준비·출발·도착·수령·실패를 최근 것부터 보여 줍니다. 2026-10-21 이전 배송은 기록이 없습니다.
      </p>

      <div className="grid grid-cols-6 items-end gap-3">
        <Label text="사건">
          <Select value={form.eventType} onChange={set('eventType')}>
            <option value="">전체</option>
            {EVENT_TYPES.map(type => <option key={type} value={type}>{DELIVERY_EVENT_LABEL[type]}</option>)}
          </Select>
        </Label>
        <Label text="로봇">
          <Select value={form.robotId} onChange={set('robotId')}>
            <option value="">전체</option>
            {(robots.data ?? []).map(robot => <option key={robot.id} value={robot.id}>{robot.name}</option>)}
          </Select>
        </Label>
        <Label text="신청 간호사">
          <Select value={form.nurseId} onChange={set('nurseId')}>
            <option value="">전체</option>
            {(nurses.data ?? []).map(nurse => <option key={nurse.id} value={nurse.id}>{nurse.name} ({nurse.employee_no})</option>)}
          </Select>
        </Label>
        <Label text="배송 번호">
          <Input type="number" min={1} value={form.deliveryId} onChange={set('deliveryId')} placeholder="#" />
        </Label>
        <Label text="시작 날짜">
          <Input type="date" value={form.fromDate} onChange={set('fromDate')} />
        </Label>
        <Label text="끝 날짜">
          <Input type="date" value={form.toDate} onChange={set('toDate')} />
        </Label>
      </div>
      <div className="flex justify-end">
        <Button variant="secondary" onClick={() => setForm(EMPTY_FILTERS)}>거르기 지우기</Button>
      </div>

      {log.isError ? (
        <LoadError what="배송 기록" error={log.error} onRetry={() => void log.refetch()} />
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>시각</Th><Th>배송</Th><Th>목적지</Th><Th>신청한 쪽</Th><Th>사건</Th><Th>누가</Th><Th>내용</Th>
            </tr>
          </thead>
          <tbody>
            {log.isPending && <tr><td colSpan={7} className="px-3 py-2 text-slate-500">불러오는 중…</td></tr>}
            {rows.map(event => (
              <tr key={event.id}>
                <Td className="whitespace-nowrap text-slate-500">{formatDateTimeSeconds(event.occurred_at)}</Td>
                <Td>#{event.delivery_id}</Td>
                <Td>{event.destination_location_name}</Td>
                <Td>{event.requester_name}{event.requester_type === 'bedside' && <span className="text-slate-500"> (병상)</span>}</Td>
                <Td><Badge value={event.event_type} label={DELIVERY_EVENT_LABEL[event.event_type]} /></Td>
                <Td>
                  {event.actor_name}
                  {event.actor_type === 'robot' && <span className="text-slate-500"> (로봇{event.actor_robot_id == null ? ' · 삭제됨' : ''})</span>}
                  {event.actor_type === 'bedside' && <span className="text-slate-500"> (병상)</span>}
                </Td>
                <Td className="text-slate-600">{describeEvent(event)}</Td>
              </tr>
            ))}
            {!log.isPending && rows.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-2 text-slate-500">기록이 없습니다</td></tr>
            )}
          </tbody>
        </Table>
      )}
      {log.hasNextPage && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={() => void log.fetchNextPage()} disabled={log.isFetchingNextPage}>
            {log.isFetchingNextPage ? '불러오는 중…' : '더 보기'}
          </Button>
        </div>
      )}
    </div>
  )
}
