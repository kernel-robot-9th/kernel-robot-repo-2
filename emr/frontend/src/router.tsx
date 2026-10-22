// =============================================================================
// 파일   : src/router.tsx
// 역할   : react-router 8 data mode — 로그인 가드(loader) + 페이지 매핑
// 작성일 : 2026-10-14
// 구성   :
//   - requireAuth   토큰 없으면 /login 으로 redirect
//   - router        createBrowserRouter
// =============================================================================
import { createBrowserRouter, redirect } from 'react-router'
import { auth } from './api/client'
import { Layout } from './components/Layout'
import { Bedside } from './pages/Bedside'
import { Deliveries } from './pages/Deliveries'
import { DeliveryLog } from './pages/DeliveryLog'
import { Login } from './pages/Login'
import { MapView } from './pages/MapView'
import { Nurses } from './pages/Nurses'
import { Password } from './pages/Password'
import { Sites } from './pages/Sites'
import { Supplies } from './pages/Supplies'

const requireAuth = () => (auth.get() ? null : redirect('/login'))

export const router = createBrowserRouter([
  { path: '/login', Component: Login },
  { path: '/bedside', Component: Bedside },   // 병상 화면 — 간호사 로그인과 별개, 병상 단말 키 (2026-10-22)
  {
    path: '/',
    Component: Layout,
    loader: requireAuth,
    children: [
      { index: true, loader: () => redirect('/deliveries') },
      { path: 'deliveries', Component: Deliveries },
      { path: 'delivery-log', Component: DeliveryLog },   // 관리자 배송 기록 (2026-10-21)
      { path: 'map', Component: MapView },
      { path: 'supplies', Component: Supplies },
      { path: 'nurses', Component: Nurses },
      { path: 'sites', Component: Sites },
      { path: 'password', Component: Password },   // 내 비밀번호 변경 (상단 링크)
    ],
  },
])
