// =============================================================================
// 파일   : src/pages/Nurses.tsx
// 역할   : 간호사 목록 + (관리자) 등록·역할 변경·비활성화·복구·비밀번호 초기화·마커 번호 배정
// 작성일 : 2026-10-14
// 구성   :
//   - parseMarkerInput    마커 번호 입력 → number | null (빈 칸=미배정)
//   - MarkerCell          마커 열. 관리자는 번호 입력, 관리자·본인은 마커 보기·인쇄 (2026-10-16)
//   - PasswordResetForm   행 안에서 임시 비밀번호 입력 (관리자)
//   - Nurses              일반 간호사는 목록만 본다. 자기 자신 행은 비활성화·역할 변경·초기화 버튼을 숨김 (백엔드도 거부)
// =============================================================================
import { useState } from 'react'
import { useIsAdmin, useMe, useNurseMutations, useNurses } from '../api/hooks'
import type { Nurse, NurseCreate, NurseRole } from '../api/types'
import { NURSE_ROLE_LABEL } from '../api/types'
import { Badge, Button, Input, Label, LoadError, PageTitle, Select, Table, Td, Th } from '../components/ui'
import { ArucoMarker } from '../features/markers/ArucoMarker'
import { ARUCO_MARKER_ID_MAX } from '../features/markers/arucoDictionary'
import { MarkerPrintDialog } from '../features/markers/MarkerPrintDialog'

const EMPTY_FORM: NurseCreate = { employee_no: '', name: '', password: '', role: 'nurse', aruco_marker_id: null }

/** 마커 번호 입력값 → 서버로 보낼 값. 빈 칸은 미배정(null), 0~49 정수가 아니면 undefined(보내지 않음).
 *  [입력] text: input 값  [출력] number | null | undefined
 */
function parseMarkerInput(text: string): number | null | undefined {
  if (text.trim() === '') return null
  const value = Number(text)
  return Number.isInteger(value) && value >= 0 && value <= ARUCO_MARKER_ID_MAX ? value : undefined
}

/** 마커 열 한 칸. 관리자는 번호를 바로 고친다(blur 시 저장, 빈 칸=해제). 마커 보기·인쇄는 관리자와 본인만.
 *  [입력] nurse / canEdit: 관리자 / canPrint: 관리자 또는 본인 / onPrint
 */
function MarkerCell({ nurse, canEdit, canPrint, onPrint }: {
  nurse: Nurse; canEdit: boolean; canPrint: boolean; onPrint: () => void
}) {
  const { update } = useNurseMutations()
  const saved = nurse.aruco_marker_id
  return (
    <div className="flex items-center gap-2">
      {canEdit ? (
        <div className="w-20">
        <Input
          key={saved ?? 'none'}   // 서버 값이 바뀌면(다른 화면·다시 불러옴) 입력칸도 새 값으로
          type="number" min={0} max={ARUCO_MARKER_ID_MAX} placeholder="없음"
          aria-label={`${nurse.name} 마커 번호`} defaultValue={saved ?? ''}
          onBlur={e => {
            const input = e.currentTarget
            const next = parseMarkerInput(input.value)
            const restore = () => { input.value = saved === null ? '' : String(saved) }
            if (next === undefined) { restore(); return }   // 범위 밖 — 저장하지 않고 되돌린다
            if (next !== saved) update.mutate({ id: nurse.id, body: { aruco_marker_id: next } }, { onError: restore })
          }}
        />
        </div>
      ) : (
        <span className="font-mono">{saved ?? <span className="text-slate-400">없음</span>}</span>
      )}
      {saved !== null && canPrint && (
        <button type="button" onClick={onPrint} title="마커 보기·인쇄" className="rounded border border-slate-200 p-0.5 hover:border-blue-400">
          <ArucoMarker arucoMarkerId={saved} className="size-7" />
        </button>
      )}
    </div>
  )
}

/** 임시 비밀번호 입력 한 줄 (관리자). 비밀번호는 평문으로 보내고 서버가 bcrypt 해시로만 저장한다.
 *  [입력] nurse: 대상 / onDone(notice): 닫기, 성공하면 안내 문구
 */
function PasswordResetForm({ nurse, onDone }: { nurse: Nurse; onDone: (notice?: string) => void }) {
  const { resetPassword } = useNurseMutations()
  const [newPassword, setNewPassword] = useState('')
  const valid = newPassword.length >= 8 && newPassword.length <= 72
  const save = () => resetPassword.mutate(
    { id: nurse.id, body: { new_password: newPassword } },
    { onSuccess: () => onDone(`${nurse.name}(${nurse.employee_no})의 비밀번호를 초기화했습니다. 임시 비밀번호를 직접 알려 주고, 로그인 후 바꾸도록 안내해 주세요.`) },
  )
  return (
    <div className="flex items-center gap-1">
      <div className="w-48">
        <Input type="password" placeholder="임시 비밀번호 (8자 이상)" autoComplete="new-password"
          value={newPassword} onChange={e => setNewPassword(e.target.value)} />
      </div>
      <Button disabled={!valid || resetPassword.isPending} onClick={save}>저장</Button>
      <Button variant="secondary" onClick={() => onDone()}>취소</Button>
    </div>
  )
}

export function Nurses() {
  const nurses = useNurses()
  const me = useMe()
  const isAdmin = useIsAdmin()
  const { create, update, deactivate } = useNurseMutations()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<NurseCreate>(EMPTY_FORM)
  const [resetTargetId, setResetTargetId] = useState<number | null>(null)
  const [printTarget, setPrintTarget] = useState<(Nurse & { aruco_marker_id: number }) | null>(null)
  const [notice, setNotice] = useState('')

  const closeReset = (message?: string) => {
    setResetTargetId(null)
    if (message) setNotice(message)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <PageTitle>간호사</PageTitle>
        {isAdmin && <Button onClick={() => setShowForm(v => !v)}>{showForm ? '닫기' : '+ 등록'}</Button>}
      </div>
      {me.data && !isAdmin && (
        <p className="text-sm text-slate-500">간호사 등록·수정·비활성화와 비밀번호 초기화는 관리자만 할 수 있습니다.</p>
      )}
      {notice && <p className="rounded bg-green-50 px-3 py-2 text-sm text-green-800">{notice}</p>}
      <p className="text-sm text-slate-500">
        마커는 신분증 대신 쓰는 ArUco 4x4_50 마커입니다(번호 0~{ARUCO_MARKER_ID_MAX}, 간호사마다 다른 번호).
        {isAdmin ? ' 번호 칸을 비우면 배정이 해제됩니다.' : ''} 마커 그림을 누르면 크게 보고 인쇄할 수 있습니다.
      </p>

      {isAdmin && showForm && (
        <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
          <div className="grid grid-cols-5 gap-3">
            <Label text="사번"><Input value={form.employee_no} onChange={e => setForm(f => ({ ...f, employee_no: e.target.value }))} placeholder="N003" /></Label>
            <Label text="이름"><Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} /></Label>
            <Label text="초기 비밀번호 (8자 이상)">
              <Input type="password" autoComplete="new-password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} />
            </Label>
            <Label text="역할">
              <Select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value as NurseRole }))}>
                <option value="nurse">일반</option><option value="admin">관리자</option>
              </Select>
            </Label>
            <Label text={`마커 번호 (0~${ARUCO_MARKER_ID_MAX}, 선택)`}>
              <Input
                type="number" min={0} max={ARUCO_MARKER_ID_MAX} placeholder="없음"
                value={form.aruco_marker_id ?? ''}
                onChange={e => setForm(f => ({ ...f, aruco_marker_id: e.target.value === '' ? null : Number(e.target.value) }))}
              />
            </Label>
          </div>
          <div className="flex items-center gap-3">
            <Button
              disabled={
                !form.employee_no || !form.name || form.password.length < 8 || create.isPending
                || parseMarkerInput(String(form.aruco_marker_id ?? '')) === undefined
              }
              onClick={() => create.mutate(form, { onSuccess: () => { setShowForm(false); setForm(EMPTY_FORM) } })}
            >
              등록
            </Button>
          </div>
        </div>
      )}

      {nurses.isError ? (
        <LoadError what="간호사 목록" error={nurses.error} onRetry={() => void nurses.refetch()} />
      ) : (
        <Table>
          <thead><tr><Th>사번</Th><Th>이름</Th><Th>역할</Th><Th>마커</Th><Th>상태</Th>{isAdmin && <Th>{' '}</Th>}</tr></thead>
          <tbody>
            {(nurses.data ?? []).map(n => {
              const isSelf = n.id === me.data?.id
              return (
                <tr key={n.id}>
                  <Td className="font-mono">{n.employee_no}</Td>
                  <Td>{n.name}{isSelf && <span className="ml-1 text-xs text-slate-400">(나)</span>}</Td>
                  <Td>
                    {isAdmin && !isSelf ? (
                      <div className="w-28">
                        <Select value={n.role} onChange={e => update.mutate({ id: n.id, body: { role: e.target.value as NurseRole } })}>
                          <option value="nurse">일반</option><option value="admin">관리자</option>
                        </Select>
                      </div>
                    ) : (
                      <Badge value={n.role} label={NURSE_ROLE_LABEL[n.role]} />
                    )}
                  </Td>
                  <Td>
                    <MarkerCell
                      nurse={n} canEdit={isAdmin} canPrint={isAdmin || isSelf}
                      onPrint={() => { if (n.aruco_marker_id !== null) setPrintTarget({ ...n, aruco_marker_id: n.aruco_marker_id }) }}
                    />
                  </Td>
                  <Td><Badge value={n.is_active ? 'active' : 'inactive'} label={n.is_active ? '활성' : '비활성'} /></Td>
                  {isAdmin && (
                    <Td>
                      {isSelf ? (
                        <span className="text-xs text-slate-400">내 비밀번호는 상단 '비밀번호 변경'에서</span>
                      ) : resetTargetId === n.id ? (
                        <PasswordResetForm nurse={n} onDone={closeReset} />
                      ) : (
                        <div className="flex gap-1">
                          <Button variant="secondary" onClick={() => { setNotice(''); setResetTargetId(n.id) }}>비밀번호 초기화</Button>
                          {n.is_active ? (
                            <Button variant="danger" onClick={() => { if (confirm(`${n.name} 비활성화?`)) deactivate.mutate(n.id) }}>비활성화</Button>
                          ) : (
                            <Button variant="secondary" onClick={() => update.mutate({ id: n.id, body: { is_active: true } })}>복구</Button>
                          )}
                        </div>
                      )}
                    </Td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}
      {printTarget && <MarkerPrintDialog nurse={printTarget} onClose={() => setPrintTarget(null)} />}
    </div>
  )
}
