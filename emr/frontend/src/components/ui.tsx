// =============================================================================
// 파일   : src/components/ui.tsx
// 역할   : 공용 UI 조각 — 버튼·입력·테이블·상태 배지·불러오기 실패 화면. 라이브러리 없이 Tailwind만
// 작성일 : 2026-10-14
// 구성   :
//   - Button, Input, Select, Label
//   - Table, Th, Td
//   - Badge             상태 색상
//   - TechnicalDetails  오류 기술 정보 접기 (관리자 전달용)
//   - LoadError         목록 조회 실패 시 표 자리에 보이는 오류 화면 + 다시 시도
//   - PageTitle
// 저장·삭제 실패는 ErrorDialog.tsx 팝업이 맡는다
// =============================================================================
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { describeError } from '../api/errorMessages'

type Variant = 'primary' | 'secondary' | 'danger'
const VARIANT: Record<Variant, string> = {
  primary: 'bg-blue-600 text-white hover:bg-blue-700',
  secondary: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-100',
  danger: 'bg-red-600 text-white hover:bg-red-700',
}

export function Button({ variant = 'primary', className = '', ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...rest}
      className={`whitespace-nowrap rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${VARIANT[variant]} ${className}`}
    />
  )
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`w-full rounded border border-slate-300 px-2 py-1.5 text-sm ${props.className ?? ''}`} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-sm ${props.className ?? ''}`} />
}

export function Label({ children, text }: { children: ReactNode; text: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-slate-600">{text}</span>
      {children}
    </label>
  )
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="w-full text-sm">{children}</table>
    </div>
  )
}
export const Th = ({ children }: { children: ReactNode }) => (
  <th className="border-b border-slate-200 bg-slate-100 px-3 py-2 text-left font-medium text-slate-600">{children}</th>
)
export const Td = ({ children, className = '' }: { children: ReactNode; className?: string }) => (
  <td className={`border-b border-slate-100 px-3 py-2 ${className}`}>{children}</td>
)

const BADGE: Record<string, string> = {
  reserved: 'bg-amber-100 text-amber-800',
  cancelled: 'bg-slate-200 text-slate-600',
  received: 'bg-green-100 text-green-800',
  dispatched: 'bg-blue-100 text-blue-800',     // 배송: 로봇 출발
  arrived: 'bg-teal-100 text-teal-800',        // 배송: 도착, 수령 대기
  failed: 'bg-red-100 text-red-800',           // 배송: 실패
  active: 'bg-green-100 text-green-800',
  inactive: 'bg-slate-200 text-slate-600',
  idle: 'bg-slate-200 text-slate-700',
  delivering: 'bg-blue-100 text-blue-800',
  charging: 'bg-amber-100 text-amber-800',
  maintenance: 'bg-red-100 text-red-800',
  admin: 'bg-violet-100 text-violet-800',   // 간호사 역할: 관리자
  nurse: 'bg-slate-100 text-slate-700',     // 간호사 역할: 일반
}
export function Badge({ value, label }: { value: string; label?: string }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${BADGE[value] ?? 'bg-slate-100'}`}>
      {label ?? value}
    </span>
  )
}

/** 오류의 상태·코드·서버 메시지를 접어 둔다. 간호사는 열 필요 없고, 문제가 계속되면 관리자에게 전달한다. */
export function TechnicalDetails({ technical }: { technical: string }) {
  return (
    <details className="text-xs text-slate-500">
      <summary className="cursor-pointer select-none">기술 정보 (관리자 전달용)</summary>
      <p className="mt-1 break-all font-mono">{technical}</p>
    </details>
  )
}

/** 목록 조회가 실패했을 때 표 자리에 보이는 오류 화면.
 *  [입력] what: 불러오려던 것 — "배송 예약 목록"처럼 받침 있는 말(뒤에 '을'이 붙는다) / error / onRetry: 다시 조회
 */
export function LoadError({ what, error, onRetry }: { what: string; error: unknown; onRetry: () => void }) {
  const description = describeError(error)
  return (
    <div role="alert" className="space-y-3 rounded border border-red-200 bg-white px-6 py-8 text-center">
      <p className="font-semibold text-slate-900">{what}을 불러오지 못했습니다</p>
      <p className="text-sm text-slate-700">{description.message}</p>
      {description.hint && <p className="text-sm text-slate-500">{description.hint}</p>}
      <Button onClick={onRetry}>다시 시도</Button>
      <TechnicalDetails technical={description.technical} />
    </div>
  )
}

export const PageTitle = ({ children }: { children: ReactNode }) => (
  <h1 className="mb-4 text-xl font-semibold">{children}</h1>
)
