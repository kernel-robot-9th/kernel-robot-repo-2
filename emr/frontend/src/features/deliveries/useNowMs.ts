// =============================================================================
// 파일   : src/features/deliveries/useNowMs.ts
// 역할   : 지금 시각(ms) 훅 — 렌더 중에 Date.now()를 부르지 않도록 상태로 두고 주기적으로 갱신 (DeliveryProgress에서 분리, 2026-10-22)
// 작성일 : 2026-10-20
// 구성   :
//   - useNowMs   배송 단계 안내('예약 시각이 지났는지')·병상 화면(최근 결과를 보여 줄지)
// =============================================================================
import { useEffect, useState } from 'react'

/** [입력] intervalMs [출력] number: 지금 시각 ms */
export function useNowMs(intervalMs = 30_000): number {
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return nowMs
}
