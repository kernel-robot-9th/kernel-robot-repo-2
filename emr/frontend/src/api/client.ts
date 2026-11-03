// =============================================================================
// 파일   : src/api/client.ts
// 역할   : fetch 래퍼 — JWT 자동 첨부, 실패를 모두 ApiRequestError로 변환
// 작성일 : 2026-10-14
// 구성   :
//   - auth                 토큰 저장/조회/삭제 (localStorage, try/catch)
//   - ApiRequestError      status + code + detail. 안내 문구는 errorMessages.ts
//   - toApiRequestError()  실패 응답 본문 → ApiRequestError ({code,detail}·FastAPI 422·본문 없음)
//   - request<T>()         공통 호출. body가 FormData면 multipart(파일 업로드). 연결 실패는 network_error, 401이면 토큰 삭제
//   - apiUrl()             <img> 등에 쓸 API 주소
//   - api                  get/post/patch/del 단축
//   - apiV2                /api/v2 호출 — 고도화 중인 기능(음성, 2026-10-26). BASE_URL의 /v1을 /v2로 바꾼 주소
//   - streamServerSentEvents()  로그인 헤더를 붙인 SSE 읽기 (EventSource는 헤더를 못 붙여 토큰이 URL에 남는다)
//   - bedsideKey / bedsideApi   병상 단말 키(X-Bedside-Api-Key) 저장·호출 — 간호사 토큰과 따로 (2026-10-22). 401이면 단말 키만 지운다
// =============================================================================
// 기본은 같은 주소의 /api/v1 (Vite 프록시가 백엔드로 넘김). 백엔드를 다른 주소로 직접 부를 때만 VITE_API_URL로 바꾼다
const BASE_URL: string = import.meta.env.VITE_API_URL || '/api/v1'

/** 브라우저가 직접 여는 API 주소 (예: 맵 이미지). [입력] path('/maps/1/image') [출력] string */
export const apiUrl = (path: string): string => BASE_URL + path
const BASE_URL_V2: string = BASE_URL.replace(/\/v1\/?$/, '/v2')
const TOKEN_KEY = 'emr_token'

export const auth = {
  get(): string | null {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set(token: string): void {
    try { localStorage.setItem(TOKEN_KEY, token) } catch { /* 사생활 모드 등 — 세션만 유지 */ }
  },
  clear(): void {
    try { localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ }
  },
}

export class ApiRequestError extends Error {
  status: number   // 0이면 서버에 닿지 못함 (서버 꺼짐·주소 틀림·CORS 차단)
  code: string     // 백엔드 오류 code (예: location_in_use) 또는 network_error·validation_error·http_<상태>
  constructor(status: number, code: string, detail: string) {
    super(detail)
    this.status = status
    this.code = code
  }
}

interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

/** 실패 응답 → ApiRequestError. 우리 형식 {code, detail} 외에 FastAPI 입력 검증(422)·본문 없음도 받는다.
 *  [입력] res: ok가 아닌 응답
 *  [출력] ApiRequestError
 */
async function toApiRequestError(res: Response): Promise<ApiRequestError> {
  let body: { code?: unknown; detail?: unknown } = {}
  try { body = await res.json() } catch { /* 본문 없음·JSON 아님 (예: 500 Internal Server Error) */ }
  if (typeof body.detail === 'string') {
    return new ApiRequestError(res.status, typeof body.code === 'string' ? body.code : `http_${res.status}`, body.detail)
  }
  if (Array.isArray(body.detail)) {
    // FastAPI 422: [{loc: ['body', 'name'], msg: '...'}] → "name: ..."
    const issues = (body.detail as ValidationIssue[]).map(issue => `${(issue.loc ?? []).slice(1).join('.')}: ${issue.msg ?? ''}`)
    return new ApiRequestError(res.status, 'validation_error', issues.join('; '))
  }
  return new ApiRequestError(res.status, `http_${res.status}`, res.statusText)
}

/** 공통 호출. body는 JSON 직렬화. 204는 undefined 반환.
 *  [입력] method, path('/supplies' 처럼 BASE_URL 뒤 경로), body?, baseUrl(기본 /api/v1)
 *  [출력] Promise<T> — 2xx가 아니거나 연결 실패면 ApiRequestError throw
 */
export async function request<T>(method: string, path: string, body?: unknown, baseUrl: string = BASE_URL): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = auth.get()
  if (token) headers.Authorization = `Bearer ${token}`
  const isMultipart = body instanceof FormData   // 경계(boundary)가 든 Content-Type은 브라우저가 붙인다
  if (body !== undefined && !isMultipart) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(baseUrl + path, {
      method,
      headers,
      body: body === undefined ? undefined : isMultipart ? body : JSON.stringify(body),
    })
  } catch (networkError) {
    // 브라우저는 연결 실패 이유를 알려주지 않고 TypeError("Failed to fetch")만 준다
    throw new ApiRequestError(0, 'network_error', networkError instanceof Error ? networkError.message : String(networkError))
  }

  if (res.status === 401) auth.clear()
  if (!res.ok) throw await toApiRequestError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  del: <T = void>(path: string) => request<T>('DELETE', path),
}

/** /api/v2 — 고도화 중인 기능(음성). 인증·오류 처리는 api와 같다 */
export const apiV2 = {
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body, BASE_URL_V2),
}

// ---------- 병상 단말 (2026-10-22) ----------
const BEDSIDE_KEY = 'emr_bedside_key'
/** 병상 단말 키 저장 — 간호사 로그인 토큰(emr_token)과 따로. localStorage를 못 쓰면 이 탭에서만 유지 */
let bedsideKeyInMemory: string | null = null
export const bedsideKey = {
  get(): string | null {
    try { return localStorage.getItem(BEDSIDE_KEY) ?? bedsideKeyInMemory } catch { return bedsideKeyInMemory }
  },
  set(key: string) {
    bedsideKeyInMemory = key
    try { localStorage.setItem(BEDSIDE_KEY, key) } catch { /* 사생활 모드 등 — 메모리에만 */ }
  },
  clear() {
    bedsideKeyInMemory = null
    try { localStorage.removeItem(BEDSIDE_KEY) } catch { /* ignore */ }
  },
}

/** 병상 단말 API 호출 (/bedside/...). 헤더 X-Bedside-Api-Key, 401이면 단말 키만 지운다(간호사 토큰은 그대로).
 *  [입력] method, path('/bedside/me'), body?  [출력] Promise<T> — 실패는 ApiRequestError */
async function bedsideRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const key = bedsideKey.get()
  if (key) headers['X-Bedside-Api-Key'] = key
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(BASE_URL + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch (networkError) {
    throw new ApiRequestError(0, 'network_error', networkError instanceof Error ? networkError.message : String(networkError))
  }
  if (res.status === 401) bedsideKey.clear()
  if (!res.ok) throw await toApiRequestError(res)
  return (await res.json()) as T
}

export const bedsideApi = {
  get: <T>(path: string) => bedsideRequest<T>('GET', path),
  post: <T>(path: string, body?: unknown) => bedsideRequest<T>('POST', path, body),
}

/** 병상 단말 키 오류인지 — 이 오류는 간호사 로그인 화면으로 보내지 않는다(main.tsx) */
export const isBedsideKeyError = (err: unknown) =>
  err instanceof ApiRequestError && err.code.startsWith('bedside_key_')

/** 서버가 보낸 SSE 한 덩어리 → { event, data }. 주석(: ping)·retry만 있는 덩어리는 null.
 *  [입력] block: 빈 줄로 나뉜 한 덩어리  [출력] { event, data } | null
 */
function parseServerSentEvent(block: string): { event: string; data: string } | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
  }
  return dataLines.length ? { event, data: dataLines.join('\n') } : null
}

/** SSE 경로를 열고 이벤트마다 onEvent를 부른다. 서버가 연결을 닫으면 끝난다 — 다시 연결은 호출자 몫.
 *  [입력] path('/notifications/stream'), onEvent(event, data), signal: 중단(로그아웃·화면 이탈), onOpen: 연결 성공 시
 *  [출력] Promise<void> — 연결 실패·2xx 아님이면 ApiRequestError throw (401이면 토큰 삭제)
 */
export async function streamServerSentEvents(
  path: string, onEvent: (event: string, data: string) => void, signal: AbortSignal, onOpen?: () => void,
): Promise<void> {
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  const token = auth.get()
  if (token) headers.Authorization = `Bearer ${token}`

  let res: Response
  try {
    res = await fetch(BASE_URL + path, { headers, signal, cache: 'no-store' })
  } catch (networkError) {
    if (signal.aborted) return
    throw new ApiRequestError(0, 'network_error', networkError instanceof Error ? networkError.message : String(networkError))
  }
  if (res.status === 401) auth.clear()
  if (!res.ok || !res.body) throw await toApiRequestError(res)
  onOpen?.()

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) return
      buffer += value.replace(/\r\n?/g, '\n')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const parsed = parseServerSentEvent(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        if (parsed) onEvent(parsed.event, parsed.data)
      }
    }
  } catch (readError) {
    if (signal.aborted) return
    throw new ApiRequestError(0, 'network_error', readError instanceof Error ? readError.message : String(readError))
  }
}
