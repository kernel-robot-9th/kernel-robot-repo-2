// =============================================================================
// 파일   : src/features/robots/RobotApiKeyDialog.tsx
// 역할   : 발급한 로봇 API 키를 한 번만 보여 주는 대화상자 (관리자) — 닫으면 다시 볼 수 없다
// 작성일 : 2026-10-19
// 구성   :
//   - RobotApiKeyDialog   키 표시 + 복사. 키는 이 컴포넌트 상태에만 있고 저장하지 않는다
//                         병상 단말 키도 같은 창을 쓴다 — title·help로 문구만 바꾼다 (2026-10-22)
// =============================================================================
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Button } from '../../components/ui'

/** [입력] robotName: 로봇(또는 병상) 이름 / issued: 발급 응답(api_key) / onClose: 닫기 (키를 버린다)
 *        title·help: 제목 뒤 꼬리말과 아래 안내 (없으면 로봇용 문구) */
export function RobotApiKeyDialog({ robotName, issued, onClose, title = '로봇 API 키', help }: {
  robotName: string; issued: { api_key: string }; onClose: () => void; title?: string; help?: ReactNode
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const keyRef = useRef<HTMLInputElement>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog && !dialog.open) dialog.showModal()
    keyRef.current?.select()
  }, [])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(issued.api_key)
      setCopied(true)
    } catch {
      keyRef.current?.select()   // http 등으로 클립보드를 못 쓰면 선택해 두고 Ctrl+C로
    }
  }

  return (
    <dialog
      ref={dialogRef} onClose={onClose} aria-labelledby="robot-key-dialog-title"
      className="m-auto w-[min(34rem,calc(100vw-2rem))] rounded-lg p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <div className="space-y-4 p-6">
        <h2 id="robot-key-dialog-title" className="font-semibold">{robotName} — {title}</h2>
        <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-900">
          이 키는 <b>지금 한 번만</b> 보입니다. 닫기 전에 {title.includes("병상") ? "병상 단말" : "로봇 설정"}에 넣어 주세요. 잃어버리면 다시 발급하면 되고, 그때 이 키는 더 쓸 수 없습니다.
        </p>
        <div className="flex gap-2">
          <input ref={keyRef} readOnly value={issued.api_key} aria-label="API 키"
            className="w-full rounded border border-slate-300 bg-slate-50 px-2 py-1.5 font-mono text-xs" onFocus={e => e.target.select()} />
          <Button variant="secondary" onClick={() => void copy()}>{copied ? '복사됨' : '복사'}</Button>
        </div>
        <p className="text-xs text-slate-500">{help ?? <>관제 PC 배송 실행기가 요청 헤더 <code>X-Robot-Api-Key</code>에 이 키를 넣어 <code>/api/v1/robot/…</code>(배송 가져가기·진행 보고·수령 확인)를 부릅니다. 키 파일은 실행기 설정 폴더에 권한 600으로 둡니다.</>}</p>
        <div className="flex justify-end">
          <Button onClick={onClose}>저장했습니다 · 닫기</Button>
        </div>
      </div>
    </dialog>
  )
}
