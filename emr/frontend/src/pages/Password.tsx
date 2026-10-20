// =============================================================================
// 파일   : src/pages/Password.tsx
// 역할   : 내 비밀번호 변경 — 현재 비밀번호를 확인한 뒤 새 비밀번호로 (POST /auth/password)
// 작성일 : 2026-10-15
// 구성   :
//   - Password   새 비밀번호는 8~72자, 확인 칸과 같아야 저장 가능. 현재 비밀번호가 틀리면 오류 팝업
// 비밀번호는 평문으로 보낸다(운영은 HTTPS로만). 서버가 bcrypt 해시와 대조하고 해시로만 저장한다
// =============================================================================
import { useState } from 'react'
import type { FormEvent } from 'react'
import { useChangePassword } from '../api/hooks'
import { Button, Input, Label, PageTitle } from '../components/ui'

export function Password() {
  const changePassword = useChangePassword()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changed, setChanged] = useState(false)

  const lengthValid = newPassword.length >= 8 && newPassword.length <= 72
  const confirmMatches = newPassword === confirmPassword
  const valid = currentPassword !== '' && lengthValid && confirmMatches

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!valid) return
    setChanged(false)
    changePassword.mutate(
      { current_password: currentPassword, new_password: newPassword },
      {
        onSuccess: () => {
          setCurrentPassword(''); setNewPassword(''); setConfirmPassword('')
          setChanged(true)
        },
      },
    )
  }

  return (
    <div className="max-w-md space-y-4">
      <PageTitle>비밀번호 변경</PageTitle>
      {changed && <p className="rounded bg-green-50 px-3 py-2 text-sm text-green-800">비밀번호를 바꿨습니다. 다음 로그인부터 새 비밀번호를 쓰세요.</p>}
      <form onSubmit={submit} className="space-y-3 rounded border border-slate-200 bg-white p-4">
        <Label text="현재 비밀번호">
          <Input type="password" autoComplete="current-password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} />
        </Label>
        <Label text="새 비밀번호 (8~72자)">
          <Input type="password" autoComplete="new-password" value={newPassword} onChange={e => setNewPassword(e.target.value)} />
        </Label>
        <Label text="새 비밀번호 확인">
          <Input type="password" autoComplete="new-password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} />
        </Label>
        {newPassword !== '' && !lengthValid && <p className="text-xs text-slate-500">새 비밀번호는 8자 이상 72자 이하여야 합니다</p>}
        {confirmPassword !== '' && !confirmMatches && <p className="text-xs text-slate-500">새 비밀번호와 확인 칸이 다릅니다</p>}
        <Button type="submit" disabled={!valid || changePassword.isPending}>
          {changePassword.isPending ? '저장 중…' : '변경'}
        </Button>
      </form>
    </div>
  )
}
