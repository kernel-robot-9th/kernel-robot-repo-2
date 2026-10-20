// =============================================================================
// 파일   : src/pages/Login.tsx
// 역할   : 간호사 로그인 — POST /auth/login → 토큰 저장 → /deliveries
// 작성일 : 2026-10-14
// 구성   :
//   - Login   React 19 useActionState 로 폼 처리 (useState 없음)
// =============================================================================
import { useActionState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { api, auth, ApiRequestError } from '../api/client'
import { describeError } from '../api/errorMessages'
import type { LoginIn, TokenOut } from '../api/types'
import { showErrorDialog } from '../components/errorDialogStore'
import { Button, Input, Label } from '../components/ui'

export function Login() {
  const nav = useNavigate()
  // 다른 화면에서 401로 쫓겨난 경우 main.tsx가 state.expired를 넘긴다
  const expired = (useLocation().state as { expired?: boolean } | null)?.expired === true

  // [입력] form: employee_no, password  [출력] 오류 문자열 또는 null
  const [error, submit, pending] = useActionState(
    async (_prev: string | null, form: FormData): Promise<string | null> => {
      const body: LoginIn = {
        employee_no: String(form.get('employee_no') ?? ''),
        password: String(form.get('password') ?? ''),
      }
      try {
        const token = await api.post<TokenOut>('/auth/login', body)
        auth.set(token.access_token)
        nav('/deliveries')
        return null
      } catch (e) {
        // 사번·비밀번호 틀림은 폼 아래에 바로, 서버 연결 실패 등은 오류 팝업으로
        if (e instanceof ApiRequestError && e.code === 'invalid_credentials') return describeError(e).message
        showErrorDialog('로그인에 실패했습니다', e)
        return null
      }
    },
    null,
  )

  return (
    <div className="flex min-h-screen items-center justify-center">
      <form action={submit} className="w-80 space-y-3 rounded border border-slate-200 bg-white p-6">
        <h1 className="text-lg font-semibold">EMR 배송 로그인</h1>
        {expired && !error && <p className="text-sm text-amber-700">로그인이 만료되었습니다. 다시 로그인해 주세요.</p>}
        <Label text="사번">
          <Input name="employee_no" placeholder="N001" autoComplete="username" required />
        </Label>
        <Label text="비밀번호">
          <Input name="password" type="password" autoComplete="current-password" required />
        </Label>
        <Button type="submit" disabled={pending} className="w-full">
          {pending ? '로그인 중…' : '로그인'}
        </Button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
    </div>
  )
}
