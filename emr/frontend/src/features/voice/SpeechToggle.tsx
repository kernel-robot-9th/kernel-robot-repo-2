// =============================================================================
// 파일   : src/features/voice/SpeechToggle.tsx
// 역할   : 상단 막대의 안내 음성 켜기·끄기 버튼 (2026-10-26) — 브라우저가 speechSynthesis를 지원하지 않으면 숨긴다
// 작성일 : 2026-10-26
// =============================================================================
import { setSpeechEnabled, speechSupported, useSpeechEnabled } from './speech'

export function SpeechToggle() {
  const enabled = useSpeechEnabled()
  if (!speechSupported) return null
  return (
    <button
      type="button"
      onClick={() => setSpeechEnabled(!enabled)}
      title={enabled ? '알림 소리 끄기' : '배송 알림을 소리로 읽어 줍니다'}
      className={`rounded px-2 py-1 ${enabled ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:bg-slate-100'}`}
    >
      {enabled ? '🔊 알림 켜짐' : '🔇 알림 꺼짐'}
    </button>
  )
}
