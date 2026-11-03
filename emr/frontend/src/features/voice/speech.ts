// =============================================================================
// 파일   : src/features/voice/speech.ts
// 역할   : 안내 음성(TTS) — 브라우저 내장 speechSynthesis로 배송 알림·음성 초안을 읽어 준다 (2026-10-26)
// 작성일 : 2026-10-26
// 구성   :
//   - speechSupported      이 브라우저에 speechSynthesis가 있는지
//   - speak()              켜져 있으면 한국어로 읽기 (앞 문장은 끊는다)
//   - setSpeechEnabled()   켜기·끄기 — 이 브라우저에만 기억(localStorage), 기본은 꺼짐
//   - useSpeechEnabled()   SpeechToggle이 구독
// 사용자 결정(2026-10-26): 서버·키 없이 브라우저 내장 음성. 목소리는 브라우저·OS마다 다르다.
// 브라우저는 사용자가 한 번 누르기 전에는 소리를 막을 수 있다 — 켜기 버튼을 누를 때 한 문장 읽어 둔다
// =============================================================================
import { useSyncExternalStore } from 'react'

const STORAGE_KEY = 'emr.speech.enabled'
export const speechSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

/** 기억해 둔 값. [입력] 없음 [출력] boolean (저장소를 못 쓰면 false) */
function readStored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

let enabled = speechSupported && readStored()
const listeners = new Set<() => void>()

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 한국어 목소리 고르기 — ko-KR 우선, 그다음 ko. 'kok'(콘칸어, Linux espeak-ng)이 'ko'로 시작해 섞이므로 정확히 비교한다 (2026-10-26).
 *  [입력] voices [출력] 목소리 또는 undefined(브라우저 기본 — lang=ko-KR로 맡긴다) */
function pickKoreanVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | undefined {
  const isKorean = (voice: SpeechSynthesisVoice) => /^ko([-_]|$)/i.test(voice.lang)
  return voices.find(voice => isKorean(voice) && /kr$/i.test(voice.lang)) ?? voices.find(isKorean)
}

/** 한국어로 읽기. 꺼져 있거나 지원하지 않으면 아무것도 안 한다. [입력] text [출력] 없음 */
export function speak(text: string): void {
  if (!enabled || !speechSupported || !text) return
  const synth = window.speechSynthesis
  synth.cancel()   // 알림이 몰리면 앞 문장을 끊고 최신 것을 읽는다
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'ko-KR'
  const koreanVoice = pickKoreanVoice(synth.getVoices())
  if (koreanVoice) utterance.voice = koreanVoice
  synth.speak(utterance)
}

/** 켜기·끄기. [입력] next [출력] 없음 */
export function setSpeechEnabled(next: boolean): void {
  enabled = speechSupported && next
  try {
    window.localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0')
  } catch { /* 저장소를 못 쓰면 이번 화면에서만 */ }
  if (!enabled && speechSupported) window.speechSynthesis.cancel()
  listeners.forEach(listener => listener())
  if (enabled) speak('안내 음성을 켰습니다.')
}

/** 지금 켜져 있는지. [입력] 없음 [출력] boolean */
export function useSpeechEnabled(): boolean {
  return useSyncExternalStore(subscribe, () => enabled)
}
