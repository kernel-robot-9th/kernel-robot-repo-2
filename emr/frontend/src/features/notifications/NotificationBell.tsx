// =============================================================================
// 파일   : src/features/notifications/NotificationBell.tsx
// 역할   : 상단 알림 종 — 재고 부족 비품 수 배지 + 누르면 목록. 실시간 연결 상태도 보여준다
// 작성일 : 2026-10-16
// 구성   :
//   - BellIcon           종 그림 (SVG)
//   - NotificationBell   버튼 + popover 목록
// =============================================================================
import { Link } from 'react-router'
import { useLowStock } from '../../api/hooks'
import { describeError } from '../../api/errorMessages'
import { Button } from '../../components/ui'

const PANEL_ID = 'low-stock-panel'

function BellIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  )
}

/** [입력] connected: 실시간 알림 연결 여부 (useNotificationStream) */
export function NotificationBell({ connected }: { connected: boolean }) {
  const lowStock = useLowStock()
  const count = lowStock.data?.length ?? 0
  const closePanel = () => document.getElementById(PANEL_ID)?.hidePopover()

  return (
    <>
      <button
        type="button" popoverTarget={PANEL_ID}
        aria-label={count ? `알림: 재고 부족 ${count}건` : '알림'}
        className="relative rounded p-1.5 text-slate-600 hover:bg-slate-100"
      >
        <BellIcon />
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-red-600 px-1 text-center text-[10px] leading-4 font-bold text-white">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>
      <div
        id={PANEL_ID} popover="auto"
        className="fixed top-12 right-4 left-auto m-0 w-80 rounded-lg border border-slate-200 bg-white p-0 text-sm shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
          <span className="font-semibold">재고 부족</span>
          <span className={`text-xs ${connected ? 'text-green-700' : 'text-slate-500'}`}>
            {connected ? '● 실시간 연결됨' : '○ 연결 끊김 · 다시 연결 중'}
          </span>
        </div>
        {lowStock.isError ? (
          <div className="space-y-2 px-4 py-3">
            <p className="text-slate-700">목록을 불러오지 못했습니다. {describeError(lowStock.error).message}</p>
            <Button variant="secondary" onClick={() => void lowStock.refetch()}>다시 시도</Button>
          </div>
        ) : count === 0 ? (
          <p className="px-4 py-3 text-slate-500">{lowStock.isPending ? '불러오는 중…' : '재고가 부족한 비품이 없습니다.'}</p>
        ) : (
          <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
            {lowStock.data?.map(supply => (
              <li key={supply.id} className="flex items-center justify-between gap-3 px-4 py-2">
                <span>{supply.name} <span className="font-mono text-xs text-slate-500">{supply.code}</span></span>
                <span className="text-right whitespace-nowrap">
                  <span className="font-semibold text-red-700">{supply.stock_qty}</span>
                  <span className="text-xs text-slate-500"> / 기준 {supply.low_stock_threshold_qty}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="border-t border-slate-100 px-4 py-2 text-right">
          <Link to="/supplies" onClick={closePanel} className="text-blue-700 hover:underline">비품 화면에서 기준 바꾸기 →</Link>
        </div>
      </div>
    </>
  )
}
