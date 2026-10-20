// =============================================================================
// 파일   : src/components/ErrorDialog.tsx
// 역할   : 오류 팝업 — 저장·삭제·취소가 실패하면 화면 가운데에 한국어 안내를 띄운다. 입력하던 화면은 그대로 둔다
// 작성일 : 2026-10-15
// 구성   :
//   - ErrorDialogHost   앱 최상단에 한 번 둔다. 열린 오류가 있으면 <dialog>로 표시 (Esc·확인으로 닫힘)
// 팝업을 여는 함수 showErrorDialog()는 errorDialogStore.ts에 있다
// =============================================================================
import { useEffect, useRef } from 'react'
import { describeError } from '../api/errorMessages'
import { closeErrorDialog, useOpenError } from './errorDialogStore'
import { Button, TechnicalDetails } from './ui'

export function ErrorDialogHost() {
  const current = useOpenError()
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (current && !dialog.open) {
      dialog.showModal()
      // showModal은 첫 포커스 대상(기술 정보 접기)에 포커스를 준다 — Enter로 바로 닫히게 확인 버튼으로 옮긴다
      dialog.querySelector<HTMLButtonElement>('[data-dialog-confirm]')?.focus()
    }
    if (!current && dialog.open) dialog.close()
  }, [current])

  const description = current ? describeError(current.error) : null
  return (
    <dialog
      ref={dialogRef}
      onClose={closeErrorDialog}   // Esc로 닫은 경우도 여기로 온다
      aria-labelledby="error-dialog-title"
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-lg p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      {current && description && (
        <div className="space-y-4 p-6">
          <div className="flex items-start gap-3">
            <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-full bg-red-100 font-bold text-red-600">!</span>
            <div className="space-y-1">
              <h2 id="error-dialog-title" className="font-semibold text-slate-900">{current.title}</h2>
              <p className="text-sm text-slate-700">{description.message}</p>
            </div>
          </div>
          {description.hint && <p className="rounded bg-slate-50 px-3 py-2 text-sm text-slate-600">{description.hint}</p>}
          <TechnicalDetails technical={description.technical} />
          <div className="flex justify-end">
            <Button data-dialog-confirm onClick={closeErrorDialog}>확인</Button>
          </div>
        </div>
      )}
    </dialog>
  )
}
