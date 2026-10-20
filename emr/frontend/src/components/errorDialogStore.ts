// =============================================================================
// 파일   : src/components/errorDialogStore.ts
// 역할   : 오류 팝업 상태 — 지금 열린 오류 하나. React 밖(main.tsx의 MutationCache)에서도 열 수 있게 모듈 상태로 둔다
// 작성일 : 2026-10-15
// 구성   :
//   - showErrorDialog()   팝업 열기 (이미 열려 있으면 새 오류로 바꿈)
//   - closeErrorDialog()  팝업 닫기
//   - useOpenError()      ErrorDialogHost가 구독
// =============================================================================
import { useSyncExternalStore } from 'react'

export interface OpenError {
  title: string    // 무엇을 하다 실패했는지 ("장소 삭제에 실패했습니다")
  error: unknown
}

let openError: OpenError | null = null
const listeners = new Set<() => void>()

function setOpenError(next: OpenError | null): void {
  openError = next
  listeners.forEach(listener => listener())
}

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 오류 팝업 열기.
 *  [입력] title: "장소 삭제에 실패했습니다" 같은 제목 / error: 요청 오류
 *  [출력] 없음
 */
export function showErrorDialog(title: string, error: unknown): void {
  setOpenError({ title, error })
}

/** 오류 팝업 닫기. [입력] 없음 [출력] 없음 */
export function closeErrorDialog(): void {
  setOpenError(null)
}

/** 지금 열린 오류. 없으면 null. [입력] 없음 [출력] OpenError | null */
export function useOpenError(): OpenError | null {
  return useSyncExternalStore(subscribe, () => openError)
}
