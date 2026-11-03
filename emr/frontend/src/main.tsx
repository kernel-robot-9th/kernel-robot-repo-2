// =============================================================================
// 파일   : src/main.tsx
// 역할   : 앱 진입 — QueryClient + Router + 오류 팝업 마운트. 401이면 로그인으로, 그 밖의 변경 실패는 팝업으로
// 작성일 : 2026-10-14
// =============================================================================
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { Mutation } from '@tanstack/react-query'
import { RouterProvider } from 'react-router'
import { ApiRequestError, isBedsideKeyError } from './api/client'
import { ErrorDialogHost } from './components/ErrorDialog'
import { showErrorDialog } from './components/errorDialogStore'
import { router } from './router'
import './index.css'

/** 401(토큰 만료·무효, 비활성 계정)이면 캐시를 비우고 로그인 화면으로 보낸다.
 *  조회(QueryCache)와 변경(MutationCache: 등록·수정·삭제·취소) 양쪽에 건다.
 *  [입력] err: 요청 오류  [출력] true면 로그인으로 보냄
 */
function redirectToLoginOn401(err: unknown): boolean {
  if (!(err instanceof ApiRequestError) || err.status !== 401) return false
  if (isBedsideKeyError(err)) return false   // 병상 화면은 간호사 로그인과 별개 — 그 화면이 키 입력으로 돌아간다 (2026-10-22)
  queryClient.clear()
  void router.navigate('/login', { state: { expired: true } })
  return true
}

/** 등록·수정·삭제·취소 실패 → 오류 팝업. 조회 실패는 각 화면의 LoadError가 표 자리에 보여준다.
 *  [입력] err / mutation: meta.action(작업 이름)을 팝업 제목에 쓴다  [출력] 없음
 */
function showMutationError(err: unknown, _variables: unknown, _context: unknown, mutation: Mutation<unknown, unknown, unknown>): void {
  if (redirectToLoginOn401(err)) return
  if (mutation.meta?.inline) return   // 화면이 직접 안내한다 (병상 화면)
  showErrorDialog(`${mutation.meta?.action ?? '요청'}에 실패했습니다`, err)
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 2_000 } },
  queryCache: new QueryCache({ onError: redirectToLoginOn401 }),
  mutationCache: new MutationCache({ onError: showMutationError }),
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <ErrorDialogHost />
    </QueryClientProvider>
  </StrictMode>,
)
