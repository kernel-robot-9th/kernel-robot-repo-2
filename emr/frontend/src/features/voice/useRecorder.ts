// =============================================================================
// 파일   : src/features/voice/useRecorder.ts
// 역할   : 브라우저 마이크 녹음 훅 (MediaRecorder) — 음성 배송 예약 (2026-10-26)
// 작성일 : 2026-10-26 (~/voice_module frontend/src/features/voice/useRecorder.ts, 2026-10-14에서 옮김)
// 구성   :
//   - useRecorder()  supported(이 주소에서 마이크를 쓸 수 있는지) · recording · start()(멈추면 Blob) · stop()
// 마이크는 HTTPS 또는 localhost에서만 된다 — 다른 PC가 http://<IP>:5173으로 들어오면 supported=false (문장 입력으로 대신)
// =============================================================================
import { useCallback, useRef, useState } from 'react'

const MAX_RECORDING_MS = 30_000   // 백엔드 한도(15MB)보다 훨씬 작게 — 30초에서 저절로 멈춘다

/** 브라우저가 지원하는 녹음 형식 중 백엔드가 받는 것. [입력] 없음 [출력] MIME 또는 ''(브라우저 기본) */
function pickMimeType(): string {
  const preferred = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  return preferred.find(type => MediaRecorder.isTypeSupported(type)) ?? ''
}

/** [입력] 없음 [출력] { supported, recording, start, stop } */
export function useRecorder() {
  const supported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined'
  const [recording, setRecording] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const timerRef = useRef<number | null>(null)

  /** 녹음 시작. [입력] 없음 [출력] 멈추면(stop·30초) 녹음 Blob — 마이크 권한이 없으면 reject */
  const start = useCallback(async (): Promise<Blob> => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = pickMimeType()
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    const chunks: Blob[] = []
    recorder.ondataavailable = event => { if (event.data.size > 0) chunks.push(event.data) }
    const done = new Promise<Blob>(resolve => {
      recorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop())   // 마이크 표시등 끄기
        if (timerRef.current !== null) window.clearTimeout(timerRef.current)
        setRecording(false)
        resolve(new Blob(chunks, { type: recorder.mimeType }))
      }
    })
    recorder.start()
    recorderRef.current = recorder
    setRecording(true)
    timerRef.current = window.setTimeout(() => { if (recorder.state === 'recording') recorder.stop() }, MAX_RECORDING_MS)
    return done
  }, [])

  /** 녹음 멈춤 — start()가 Blob으로 끝난다. [입력] 없음 [출력] 없음 */
  const stop = useCallback(() => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
  }, [])

  return { supported, recording, start, stop }
}
