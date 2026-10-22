// =============================================================================
// 파일   : src/components/Layout.tsx
// 역할   : 로그인 후 공통 틀 — 좌측 메뉴 + 상단 알림 종·사용자(역할) + 비밀번호 변경 + 로그아웃
//          실시간 알림 연결(useNotificationStream)과 토스트, 도착 수령 마커 창(ReceiptMarkerWatcher, 2026-10-20)도 여기서 한 번만 둔다
// 작성일 : 2026-10-14
// 구성   :
//   - NAV      메뉴 정의 (경로·라벨, adminOnly는 관리자에게만 보임 — 실제 차단은 백엔드 403)
//   - Layout   <Outlet/>으로 하위 페이지 렌더
// =============================================================================
import { NavLink, Outlet, useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { auth } from '../api/client'
import { useIsAdmin, useMe } from '../api/hooks'
import { NURSE_ROLE_LABEL } from '../api/types'
import { ReceiptMarkerWatcher } from '../features/deliveries/ReceiptMarkerWatcher'
import { NotificationBell } from '../features/notifications/NotificationBell'
import { Toasts } from '../features/notifications/Toasts'
import { useNotificationStream } from '../features/notifications/useNotificationStream'
import { Badge, Button } from './ui'

const NAV: { to: string; label: string; adminOnly?: boolean }[] = [
  { to: '/deliveries', label: '배송 예약' },
  { to: '/map', label: '맵' },
  { to: '/supplies', label: '비품' },
  { to: '/nurses', label: '간호사' },
  { to: '/sites', label: '장소·맵·로봇·병상' },
  { to: '/delivery-log', label: '배송 기록', adminOnly: true },   // 2026-10-21
]

export function Layout() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const me = useMe()
  const isAdmin = useIsAdmin()
  const { connected } = useNotificationStream()

  const logout = () => {
    auth.clear()
    qc.clear()
    nav('/login')
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-48 border-r border-slate-200 bg-white p-4">
        <div className="mb-6 text-lg font-bold">EMR 배송</div>
        <nav className="flex flex-col gap-1">
          {NAV.filter(n => !n.adminOnly || isAdmin).map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `rounded px-3 py-2 text-sm ${isActive ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-700 hover:bg-slate-100'}`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-end gap-3 border-b border-slate-200 bg-white px-6 py-2 text-sm">
          <NotificationBell connected={connected} />
          <span className="text-slate-600">
            {me.data ? `${me.data.name} (${me.data.employee_no})` : '…'}
          </span>
          {me.data && <Badge value={me.data.role} label={NURSE_ROLE_LABEL[me.data.role]} />}
          <NavLink to="/password" className="text-slate-600 underline-offset-2 hover:underline">비밀번호 변경</NavLink>
          <Button variant="secondary" onClick={logout}>로그아웃</Button>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
      <Toasts />
      <ReceiptMarkerWatcher />
    </div>
  )
}
