// =============================================================================
// 파일   : src/features/notifications/toastStore.ts
// 역할   : 알림 토스트 상태 — 화면 오른쪽 아래에 잠깐 뜨는 알림 목록. 모듈 상태라 React 밖에서도 띄울 수 있다
// 작성일 : 2026-10-16
// 구성   :
//   - showToast()     토스트 추가 (TOAST_VISIBLE_MS 뒤 자동으로 사라짐)
//   - dismissToast()  닫기
//   - useToasts()     Toasts가 구독
// =============================================================================
import { useSyncExternalStore } from 'react'

export const TOAST_VISIBLE_MS = 10_000
const MAX_TOASTS = 5   // 한꺼번에 많이 오면 오래된 것부터 버린다

/** warning: 확인이 필요한 알림(재고 부족) / success: 끝난 일(수령 완료) / info: 진행(출발·도착) / error: 실패 */
export type ToastTone = 'warning' | 'success' | 'info' | 'error'

export interface Toast {
  id: number
  title: string
  body: string
  tone: ToastTone
}

let toasts: Toast[] = []
let nextToastId = 1
const listeners = new Set<() => void>()

function setToasts(next: Toast[]): void {
  toasts = next
  listeners.forEach(listener => listener())
}

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 토스트 띄우기.
 *  [입력] title: 굵게 보일 첫 줄 / body: 설명 / tone: 색 (기본 warning)
 *  [출력] 없음
 */
export function showToast(title: string, body: string, tone: ToastTone = 'warning'): void {
  const toast = { id: nextToastId++, title, body, tone }
  setToasts([...toasts, toast].slice(-MAX_TOASTS))
  window.setTimeout(() => dismissToast(toast.id), TOAST_VISIBLE_MS)
}

/** 토스트 닫기. [입력] toastId [출력] 없음 */
export function dismissToast(toastId: number): void {
  if (toasts.some(toast => toast.id === toastId)) setToasts(toasts.filter(toast => toast.id !== toastId))
}

/** 지금 보이는 토스트들. [입력] 없음 [출력] Toast[] */
export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, () => toasts)
}
