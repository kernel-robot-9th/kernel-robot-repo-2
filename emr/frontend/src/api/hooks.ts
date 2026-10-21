// =============================================================================
// 파일   : src/api/hooks.ts
// 역할   : TanStack Query 훅 — 리소스별 조회/변경. 화면은 fetch를 직접 부르지 않는다
// 작성일 : 2026-10-14
// 구성   :
//   - keys            queryKey 상수
//   - Register        mutation meta 타입 — meta.action은 실패 팝업 제목("장소 삭제에 실패했습니다")에 쓰인다
//   - useMe / useIsAdmin / useChangePassword   /auth/me, /auth/password
//   - useSupplies / useSupplyMutations
//   - useNurses   / useNurseMutations          (등록·수정·비활성화·비밀번호 초기화는 관리자)
//   - useMaps, useLocations, useRobots (+ mutations — 변경은 관리자). useMapMutations: 맵 파일 업로드·교체·삭제
//   - useDeliveries / useDeliveryMutations     (재고가 바뀌므로 비품 목록·재고 부족 목록도 다시 불러옴)
//   - useDeliveryEvents                        배송 한 건의 기록 (본인·관리자) — 2026-10-21
//   - useDeliveryEventLog                      관리자 배송 기록 화면 (거르기 + 더 보기) — 2026-10-21
//   - useLowStock                              재고 부족 비품 (알림창). 실시간 갱신은 features/notifications
// =============================================================================
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  AdminDeliveryEvent, Delivery, DeliveryCreate, DeliveryEvent, DeliveryEventFilters, DeliveryUpdate,
  Location, MapInfo, Nurse, NurseCreate, NurseUpdate, PasswordChange, PasswordReset,
  Robot, RobotApiKey, Supply, SupplyCreate, SupplyUpdate,
} from './types'
import { ACTIVE_DELIVERY_STATUSES } from './types'

declare module '@tanstack/react-query' {
  interface Register {
    mutationMeta: { action: string }   // 작업 이름. main.tsx가 실패 시 "<action>에 실패했습니다" 팝업을 띄운다
  }
}

export const keys = {
  me: ['me'] as const,
  supplies: ['supplies'] as const,
  nurses: ['nurses'] as const,
  maps: ['maps'] as const,
  locations: ['locations'] as const,
  robots: ['robots'] as const,
  deliveries: ['deliveries'] as const,
  lowStock: ['notifications', 'low-stock'] as const,
  deliveryEventLog: ['delivery-events'] as const,
}

// ---------- 인증 ----------
export const useMe = () =>
  useQuery({ queryKey: keys.me, queryFn: () => api.get<Nurse>('/auth/me'), retry: false })

/** 로그인한 간호사가 관리자인지. 화면에서 관리자 전용 버튼을 숨기는 용도 — 실제 차단은 백엔드(403)가 한다 */
export const useIsAdmin = () => useMe().data?.role === 'admin'

/** 내 비밀번호 변경. 비밀번호는 평문으로 보낸다(운영은 HTTPS로만) — 서버가 해시와 대조·저장 */
export const useChangePassword = () =>
  useMutation({
    mutationFn: (body: PasswordChange) => api.post<void>('/auth/password', body),
    meta: { action: '비밀번호 변경' },
  })

// ---------- 비품 ----------
export const useSupplies = () =>
  useQuery({ queryKey: keys.supplies, queryFn: () => api.get<Supply[]>('/supplies') })

export function useSupplyMutations() {
  const qc = useQueryClient()
  // 재고·알림 기준이 바뀌면 재고 부족 목록도 바뀐다 (실시간 알림이 끊겨 있어도 맞도록 직접 다시 불러온다)
  const invalidate = () => Promise.all([
    qc.invalidateQueries({ queryKey: keys.supplies }),
    qc.invalidateQueries({ queryKey: keys.lowStock }),
  ])
  return {
    create: useMutation({ mutationFn: (b: SupplyCreate) => api.post<Supply>('/supplies', b), onSuccess: invalidate, meta: { action: '비품 등록' } }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: SupplyUpdate }) => api.patch<Supply>(`/supplies/${id}`, body),
      onSuccess: invalidate,
      meta: { action: '비품 수정' },
    }),
    remove: useMutation({ mutationFn: (id: number) => api.del(`/supplies/${id}`), onSuccess: invalidate, meta: { action: '비품 삭제' } }),
  }
}

/** 지금 재고가 알림 기준 이하인 비품. 실시간 알림(useNotificationStream)이 오면 다시 불러온다 */
export const useLowStock = () =>
  useQuery({ queryKey: keys.lowStock, queryFn: () => api.get<Supply[]>('/notifications/low-stock') })

// ---------- 간호사 ----------
export const useNurses = () =>
  useQuery({ queryKey: keys.nurses, queryFn: () => api.get<Nurse[]>('/nurses') })

export function useNurseMutations() {
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: keys.nurses })
  return {
    create: useMutation({ mutationFn: (b: NurseCreate) => api.post<Nurse>('/nurses', b), onSuccess: invalidate, meta: { action: '간호사 등록' } }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: NurseUpdate }) => api.patch<Nurse>(`/nurses/${id}`, body),
      onSuccess: invalidate,
      meta: { action: '간호사 정보 수정' },
    }),
    deactivate: useMutation({ mutationFn: (id: number) => api.del(`/nurses/${id}`), onSuccess: invalidate, meta: { action: '간호사 비활성화' } }),
    resetPassword: useMutation({
      mutationFn: ({ id, body }: { id: number; body: PasswordReset }) => api.post<void>(`/nurses/${id}/password-reset`, body),
      meta: { action: '비밀번호 초기화' },
    }),
  }
}

// ---------- 맵 · 장소 · 로봇 ----------
export const useMaps = () =>
  useQuery({ queryKey: keys.maps, queryFn: () => api.get<MapInfo[]>('/maps') })
export const useLocations = () =>
  useQuery({ queryKey: keys.locations, queryFn: () => api.get<Location[]>('/locations') })
export const useRobots = () =>
  useQuery({ queryKey: keys.robots, queryFn: () => api.get<Robot[]>('/robots') })

/** 맵 파일 업로드 본문 — map_server yaml + 이미지(PGM·PNG) */
export interface MapUpload {
  name: string
  mapYaml: File
  mapImage: File
}
const mapFilesForm = (mapYaml: File, mapImage: File, name?: string): FormData => {
  const form = new FormData()
  if (name !== undefined) form.append('name', name)
  form.append('map_yaml', mapYaml)
  form.append('map_image', mapImage)
  return form
}

export function useMapMutations() {
  const qc = useQueryClient()
  // 맵이 바뀌면 장소 응답에 실린 맵 정보도 바뀐다
  const invalidate = () => Promise.all([
    qc.invalidateQueries({ queryKey: keys.maps }),
    qc.invalidateQueries({ queryKey: keys.locations }),
  ])
  return {
    upload: useMutation({
      mutationFn: ({ name, mapYaml, mapImage }: MapUpload) => api.post<MapInfo>('/maps/upload', mapFilesForm(mapYaml, mapImage, name)),
      onSuccess: invalidate,
      meta: { action: '맵 등록' },
    }),
    replaceFiles: useMutation({
      mutationFn: ({ id, mapYaml, mapImage }: { id: number; mapYaml: File; mapImage: File }) =>
        api.put<MapInfo>(`/maps/${id}/files`, mapFilesForm(mapYaml, mapImage)),
      onSuccess: invalidate,
      meta: { action: '맵 파일 교체' },
    }),
    remove: useMutation({ mutationFn: (id: number) => api.del(`/maps/${id}`), onSuccess: invalidate, meta: { action: '맵 삭제' } }),
  }
}

export function useLocationMutations() {
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: keys.locations })
  return {
    create: useMutation({ mutationFn: (b: Omit<Location, 'id'>) => api.post<Location>('/locations', b), onSuccess: invalidate, meta: { action: '장소 등록' } }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<Omit<Location, 'id'>> }) =>
        api.patch<Location>(`/locations/${id}`, body),
      onSuccess: invalidate,
      meta: { action: '장소 수정' },
    }),
    remove: useMutation({ mutationFn: (id: number) => api.del(`/locations/${id}`), onSuccess: invalidate, meta: { action: '장소 삭제' } }),
  }
}

export function useRobotMutations() {
  const qc = useQueryClient()
  const invalidate = () => qc.invalidateQueries({ queryKey: keys.robots })
  return {
    create: useMutation({ mutationFn: (b: Pick<Robot, 'name' | 'robot_type' | 'status'>) => api.post<Robot>('/robots', b), onSuccess: invalidate, meta: { action: '로봇 등록' } }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Partial<Pick<Robot, 'name' | 'status' | 'home_location_id'>> }) =>
        api.patch<Robot>(`/robots/${id}`, body),
      onSuccess: invalidate,
      meta: { action: '로봇 수정' },
    }),
    remove: useMutation({ mutationFn: (id: number) => api.del(`/robots/${id}`), onSuccess: invalidate, meta: { action: '로봇 삭제' } }),
    // 수령 확인 API용 로봇별 키 (관리자). 발급 응답의 키는 다시 볼 수 없다
    issueApiKey: useMutation({
      mutationFn: (id: number) => api.post<RobotApiKey>(`/robots/${id}/api-key`),
      onSuccess: invalidate,
      meta: { action: '로봇 키 발급' },
    }),
    revokeApiKey: useMutation({ mutationFn: (id: number) => api.del(`/robots/${id}/api-key`), onSuccess: invalidate, meta: { action: '로봇 키 폐기' } }),
  }
}

// ---------- 배송 ----------
/** 로봇이 상태를 바꾸므로 다시 불러온다 — 로봇이 맡아 진행 중인 배송이 있으면 5초, 없으면 30초 (2026-10-20) */
export const DELIVERIES_REFETCH_MS = 30_000
export const ACTIVE_DELIVERIES_REFETCH_MS = 5_000
export const useDeliveries = () =>
  useQuery({
    queryKey: keys.deliveries,
    queryFn: () => api.get<Delivery[]>('/deliveries'),
    refetchInterval: query =>
      query.state.data?.some(delivery => ACTIVE_DELIVERY_STATUSES.includes(delivery.status))
        ? ACTIVE_DELIVERIES_REFETCH_MS : DELIVERIES_REFETCH_MS,
  })

export function useDeliveryMutations() {
  const qc = useQueryClient()
  // 예약·변경·취소는 재고도 바꾼다 (예약 시 차감, 취소 시 복구) — 비품 목록도 다시 불러온다
  const invalidate = () => Promise.all([
    qc.invalidateQueries({ queryKey: keys.deliveries }),
    qc.invalidateQueries({ queryKey: keys.supplies }),
    qc.invalidateQueries({ queryKey: keys.lowStock }),
  ])
  return {
    create: useMutation({ mutationFn: (b: DeliveryCreate) => api.post<Delivery>('/deliveries', b), onSuccess: invalidate, meta: { action: '배송 예약' } }),
    // 변경·취소는 실패해도(409: 이미 취소됨 등) 목록을 다시 불러와 화면을 서버 상태에 맞춘다
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: DeliveryUpdate }) => api.patch<Delivery>(`/deliveries/${id}`, body),
      onSettled: invalidate,
      meta: { action: '배송 예약 변경' },
    }),
    cancel: useMutation({
      mutationFn: (id: number) => api.post<Delivery>(`/deliveries/${id}/cancel`),
      onSettled: invalidate,
      meta: { action: '배송 예약 취소' },
    }),
  }
}

// ---------- 배송 기록 (2026-10-21, 로드맵 4단계) ----------
/** 배송 한 건의 기록, 일어난 순서. 키가 deliveries 아래라 예약·변경·취소 뒤 무효화에 같이 걸린다.
 *  [입력] deliveryId: null이면 부르지 않음 (창이 닫혀 있을 때) */
export const useDeliveryEvents = (deliveryId: number | null) =>
  useQuery({
    queryKey: [...keys.deliveries, deliveryId, 'events'],
    queryFn: () => api.get<DeliveryEvent[]>(`/deliveries/${deliveryId}/events`),
    enabled: deliveryId != null,
  })

export const DELIVERY_EVENT_PAGE_SIZE = 50
/** 관리자 배송 기록 — 최근 것부터 50개씩 '더 보기'. 조건이 바뀌면 처음부터.
 *  [입력] filters: 비어 있는 값은 보내지 않는다 */
export const useDeliveryEventLog = (filters: DeliveryEventFilters) =>
  useInfiniteQuery({
    queryKey: [...keys.deliveryEventLog, filters],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: String(DELIVERY_EVENT_PAGE_SIZE), offset: String(pageParam) })
      for (const [name, value] of Object.entries(filters)) {
        if (value !== undefined && value !== '') params.set(name, String(value))
      }
      return api.get<AdminDeliveryEvent[]>(`/delivery-events?${params}`)
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) =>
      lastPage.length < DELIVERY_EVENT_PAGE_SIZE ? undefined : pages.length * DELIVERY_EVENT_PAGE_SIZE,
  })
