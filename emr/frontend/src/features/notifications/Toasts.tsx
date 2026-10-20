// =============================================================================
// 파일   : src/features/notifications/Toasts.tsx
// 역할   : 알림 토스트 표시 — 화면 오른쪽 아래. 로그인 후 화면(Layout)에 한 번 둔다
// 작성일 : 2026-10-16
// =============================================================================
import { dismissToast, useToasts } from './toastStore'
import type { ToastTone } from './toastStore'

const TONE_CLASS: Record<ToastTone, { box: string; title: string }> = {
  warning: { box: 'border-amber-300', title: 'text-amber-800' },
  success: { box: 'border-green-300', title: 'text-green-800' },
  info: { box: 'border-blue-300', title: 'text-blue-800' },
  error: { box: 'border-red-400', title: 'text-red-700' },
}

export function Toasts() {
  const toasts = useToasts()
  return (
    <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2 print:hidden">
      {toasts.map(toast => (
        <div key={toast.id} role="status" className={`pointer-events-auto rounded-lg border bg-white p-3 shadow-lg ${TONE_CLASS[toast.tone].box}`}>
          <div className="flex items-start justify-between gap-2">
            <p className={`text-sm font-semibold ${TONE_CLASS[toast.tone].title}`}>{toast.title}</p>
            <button type="button" aria-label="알림 닫기" onClick={() => dismissToast(toast.id)}
              className="-mt-1 rounded px-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">×</button>
          </div>
          <p className="mt-1 text-sm text-slate-700">{toast.body}</p>
        </div>
      ))}
    </div>
  )
}
