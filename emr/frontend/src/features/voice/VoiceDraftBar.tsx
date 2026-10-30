// =============================================================================
// 파일   : src/features/voice/VoiceDraftBar.tsx
// 역할   : 배송 예약 폼 위의 "말로 예약" 막대 — 녹음(또는 문장) → 서버 초안 → onDraft로 폼을 채운다 (2026-10-26)
// 작성일 : 2026-10-26 (~/voice_module VoiceRequestPanel.tsx를 줄여 옮김 — 확인 화면은 배송 예약 폼이 맡는다)
// 구성   :
//   - describeDraft()  초안을 읽어 줄 한 문장 ("A 약품 2개, 101호. 확인 후 예약을 눌러 주세요.")
//   - VoiceDraftBar    🎤 말하기/멈추기 · 문장 입력 · 받아 적은 문장과 경고 표시
// 예약은 여기서 만들지 않는다 — 간호사가 폼에서 보고 '예약'을 눌러야 한다(사용자 결정 2026-10-26)
// =============================================================================
import { useState } from 'react'
import { useVoiceDraftMutations } from '../../api/hooks'
import type { VoiceDraft } from '../../api/types'
import { VOICE_WARNING_LABEL } from '../../api/types'
import { Button, Input } from '../../components/ui'
import { speak } from './speech'
import { useRecorder } from './useRecorder'

/** [입력] draft [출력] 읽어 줄 문장 */
function describeDraft(draft: VoiceDraft): string {
  const items = draft.items.map(item => `${item.supply_name ?? item.spoken_name} ${item.quantity}개`).join(', ')
  const where = draft.location.location_name ?? '목적지 미정'
  return `${items || '품목 없음'}, ${where}. 확인 후 신청을 눌러 주세요.`
}

export function VoiceDraftBar({ onDraft }: { onDraft: (draft: VoiceDraft) => void }) {
  const { supported, recording, start, stop } = useRecorder()
  const { fromAudio, fromText } = useVoiceDraftMutations()
  const [text, setText] = useState('')
  const [lastDraft, setLastDraft] = useState<VoiceDraft | null>(null)
  const [micError, setMicError] = useState(false)
  const busy = fromAudio.isPending || fromText.isPending

  const handleDraft = (draft: VoiceDraft) => {
    setLastDraft(draft)
    onDraft(draft)
    speak(describeDraft(draft))
  }

  const toggleRecording = async () => {
    if (recording) { stop(); return }
    setMicError(false)
    let audio: Blob
    try {
      audio = await start()
    } catch {
      setMicError(true)   // 권한 거부·마이크 없음
      return
    }
    fromAudio.mutate(audio, { onSuccess: handleDraft })
  }

  const submitText = () => {
    const sentence = text.trim()
    if (sentence) fromText.mutate(sentence, { onSuccess: draft => { handleDraft(draft); setText('') } })
  }

  return (
    <div className="space-y-2 rounded border border-blue-100 bg-blue-50/50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-700">말로 신청</span>
        {supported && (
          <Button onClick={() => void toggleRecording()} disabled={busy} variant={recording ? 'danger' : 'primary'}>
            {recording ? '■ 멈추고 보내기' : '🎤 말하기'}
          </Button>
        )}
        <div className="min-w-48 flex-1">
          <Input value={text} placeholder="예: 101호에 A 약품 두 개" maxLength={500}
            onChange={event => setText(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') submitText() }} />
        </div>
        <Button variant="secondary" onClick={submitText} disabled={busy || text.trim() === ''}>문장으로</Button>
        {busy && <span className="text-xs text-slate-500">알아듣는 중…</span>}
      </div>
      {!supported && (
        <p className="text-xs text-slate-500">이 주소(http)에서는 브라우저가 마이크를 막습니다 — 문장으로 입력해 주세요. 녹음은 이 서버 PC(localhost)나 HTTPS에서 됩니다.</p>
      )}
      {micError && <p className="text-xs text-amber-700">마이크를 쓸 수 없습니다 — 브라우저의 마이크 권한을 확인하거나 문장으로 입력해 주세요.</p>}
      {recording && <p className="text-xs text-red-700">● 녹음 중 — 말한 뒤 '멈추고 보내기'를 누르세요 (30초에서 저절로 멈춤)</p>}
      {lastDraft && (
        <div className="text-sm">
          <p className="text-slate-700">들은 말: “{lastDraft.transcript}”</p>
          {lastDraft.warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs text-amber-700">
              {lastDraft.warnings.map(warning => <li key={warning}>{VOICE_WARNING_LABEL[warning]}</li>)}
            </ul>
          )}
          <p className="mt-1 text-xs text-slate-500">아래 폼에 채웠습니다. 확인한 뒤 '신청'을 눌러야 신청됩니다.</p>
        </div>
      )}
    </div>
  )
}
