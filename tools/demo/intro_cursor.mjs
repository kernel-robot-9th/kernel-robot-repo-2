// EMR 배송 웹페이지 기능 소개 영상 (2026-11-02 사용자: 자막 없이, 배송 기준 웹페이지 소개 하나, 마우스 커서 보이게).
// 실제 마우스 이벤트(CDP Input)로 움직이고 누른다. 화면에 커서 그림을 얹어 마우스를 따라가게 한다.
// ⚠️ '신청'은 누르지 않는다 — 누르면 FMS 주문이 나가 실제 Pinky가 움직인다. 폼은 채운 뒤 '닫기'.
// 11-02 손봄(사용자): 앞뒤 빈 시간 줄임, select는 펼친 목록을 그려 고르는 모습이 보이게,
//   녹화 브라우저에서만 응답을 고침 — 신청 목록의 취소된 줄 숨김, 지도 로봇은 연결됨·대기로 (DB·FMS는 그대로)
// 11-02 2차: 장면마다 자막 글을 시각과 함께 <frames_dir>/captions.json에 남긴다 — 화면에는 안 그리고 intro_video.sh가 아래 띠에 넣는다
// node intro_cursor.mjs <frames_dir>
import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const [dir] = process.argv.slice(2)
mkdirSync(dir, { recursive: true })
const W = 1280, H = 800, FPS = 10, PORT = 9352
const chrome = spawn('google-chrome', ['--headless=new', `--remote-debugging-port=${PORT}`, `--window-size=${W},${H}`,
  `--user-data-dir=${mkdtempSync(join(tmpdir(), 'cdp-'))}`, '--no-first-run', '--lang=ko-KR', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' })
const sleep = ms => new Promise(r => setTimeout(r, ms))

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl)
  await new Promise(r => ws.addEventListener('open', r, { once: true }))
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data)
    if (pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } else if (m.method) onEvent(m)
  })
  return (method, params = {}) => new Promise(r => { const n = ++id; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })) })
}

// 녹화 화면에서만 응답을 고친다: 신청 목록은 취소된 줄을 빼고, 지도 로봇은 연결됨·대기로 보이게
const REWRITE = [
  { pattern: '*/api/v1/deliveries', fix: rows => rows.filter(d => d.status !== 'cancelled') },
  { pattern: '*/api/v1/robot-positions*', fix: body => ({ ...body, robots: body.robots.map(r => ({ ...r, online: true, is_stale: false, state: 'idle' })) }) },
]
const globToRegExp = g => new RegExp('^' + g.split('*').map(s => s.replace(/[.?+^${}()|[\]\\]/g, '\\$&')).join('.*') + '$')
async function onEvent(m) {
  if (m.method !== 'Fetch.requestPaused') return
  const { requestId, request, responseStatusCode, responseHeaders } = m.params
  const rule = REWRITE.find(r => globToRegExp(r.pattern).test(request.url))
  if (!rule || request.method !== 'GET' || responseStatusCode !== 200) return send('Fetch.continueRequest', { requestId })
  const got = (await send('Fetch.getResponseBody', { requestId })).result
  const text = got.base64Encoded ? Buffer.from(got.body, 'base64').toString('utf8') : got.body
  let out = text
  try { out = JSON.stringify(rule.fix(JSON.parse(text))) } catch (e) { console.log('응답 고치기 실패:', request.url, e.message) }
  const headers = responseHeaders.filter(h => !/^(content-length|content-encoding)$/i.test(h.name))
  await send('Fetch.fulfillRequest', { requestId, responseCode: 200, responseHeaders: headers, body: Buffer.from(out).toString('base64') })
}

// 페이지에 얹는 커서: 마우스를 따라가는 화살표 + 누를 때 퍼지는 원. 새 문서마다 다시 넣는다
const CURSOR_JS = `
(() => {
  const put = () => {
    if (document.getElementById('demo-cursor') || !document.body) return
    const c = document.createElement('div'); c.id = 'demo-cursor'
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2 L4 19 L8.6 14.8 L11.6 21.6 L14.4 20.4 L11.5 13.7 L17.8 13.7 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>'
    Object.assign(c.style, { position: 'fixed', left: '0px', top: '0px', zIndex: 2147483647, pointerEvents: 'none',
      transform: 'translate(' + (window.__cx || 640) + 'px,' + (window.__cy || 400) + 'px)', filter: 'drop-shadow(0 1px 2px rgba(0,0,0,.35))' })
    document.body.appendChild(c)
  }
  document.addEventListener('mousemove', e => { window.__cx = e.clientX; window.__cy = e.clientY; put()
    const c = document.getElementById('demo-cursor'); if (c) c.style.transform = 'translate(' + (e.clientX - 3) + 'px,' + (e.clientY - 2) + 'px)' }, true)
  document.addEventListener('mousedown', e => {
    const r = document.createElement('div')
    Object.assign(r.style, { position: 'fixed', left: (e.clientX - 18) + 'px', top: (e.clientY - 18) + 'px', width: '36px', height: '36px',
      borderRadius: '50%', border: '3px solid rgba(37,99,235,.85)', background: 'rgba(37,99,235,.18)', zIndex: 2147483646, pointerEvents: 'none',
      transition: 'transform .45s ease-out, opacity .45s ease-out', transform: 'scale(.4)', opacity: '1' })
    document.body.appendChild(r); requestAnimationFrame(() => { r.style.transform = 'scale(1.5)'; r.style.opacity = '0' }); setTimeout(() => r.remove(), 600)
  }, true)
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', put); else put()
})()`

// 요소 찾기 (페이지 안): 가운데 좌표를 돌려준다
const FIND_JS = `
  const center = el => { if (!el) return null; el.scrollIntoView({ block: 'nearest' }); const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } }
  const byText = (sel, text, root = document) => [...root.querySelectorAll(sel)].find(b => b.textContent.trim() === text || b.textContent.trim().startsWith(text))
  const form = () => [...document.querySelectorAll('h2')].find(h => h.textContent.trim() === '새 물품 신청')?.parentElement
  const row = no => [...document.querySelectorAll('tbody tr')].find(tr => tr.querySelector('td')?.textContent.trim() === String(no))
  const setVal = (el, v) => { const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, String(v)); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })) }
`
let send
const evaluate = async body => (await send('Runtime.evaluate', { expression: `(() => { ${FIND_JS} ${body} })()`, returnByValue: true })).result?.result?.value

// ---- 녹화: 따로 도는 고리가 경과 시간에 맞춰 장면을 채운다 (늦은 장면은 같은 그림을 겹쳐 넣어 길이를 맞춤)
let recording = true, frame = 0
const t0 = Date.now()
const captions = []   // [{ t: 녹화 시작부터 초, text }]
const mark = text => captions.push({ t: (Date.now() - t0) / 1000, text })
async function recorder() {
  let last = null
  while (recording) {
    const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 92 })
    if (shot.result?.data) last = Buffer.from(shot.result.data, 'base64')
    const want = Math.floor((Date.now() - t0) / 1000 * FPS)
    while (last && frame <= want) writeFileSync(join(dir, `f${String(frame++).padStart(5, '0')}.jpg`), last)
    await sleep(15)
  }
}

// ---- 마우스
let mx = 640, my = 420
const ease = t => t < .5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2
async function moveTo(x, y, ms = 700) {
  const fx = mx, fy = my, steps = Math.max(8, Math.round(ms / 16))
  for (let i = 1; i <= steps; i++) {
    const k = ease(i / steps)
    mx = fx + (x - fx) * k; my = fy + (y - fy) * k
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: mx, y: my })
    await sleep(ms / steps)
  }
}
async function press() {
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: mx, y: my, button: 'left', clickCount: 1 })
  await sleep(90)
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: mx, y: my, button: 'left', clickCount: 1 })
}
async function hoverAt(findBody, { ms = 700, wait = 600 } = {}) {   // 올리기만 (누르지 않음)
  const p = await evaluate(findBody)
  if (!p) { console.log('못 찾음:', findBody.slice(0, 80)); return false }
  await moveTo(p.x, p.y, ms)
  await sleep(wait)
  return true
}
async function clickAt(findBody, { ms = 700, wait = 600 } = {}) {
  if (!await hoverAt(findBody, { ms, wait: 250 })) return false
  await press()
  await sleep(wait)
  return true
}
// select는 실제로 누르면 목록 창이 따로 떠서 녹화에 안 보인다 → 누른 뒤 펼친 목록을 페이지에 그려, 커서로 항목을 골라 누른다
const LIST_JS = `
  const showList = (el, value) => {
    document.getElementById('demo-list')?.remove()
    if (!document.getElementById('demo-list-style')) {
      const st = document.createElement('style'); st.id = 'demo-list-style'
      st.textContent = '#demo-list div{padding:5px 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}#demo-list div.sel{background:#e2e8f0}#demo-list div:hover{background:#2563eb;color:#fff}'
      document.head.appendChild(st)
    }
    const r = el.getBoundingClientRect(), box = document.createElement('div'); box.id = 'demo-list'
    const opts = [...el.options].filter(o => o.value !== '')
    box.innerHTML = opts.map(o => '<div data-v="' + o.value + '"' + (o.value === el.value ? ' class="sel"' : '') + '>' + o.textContent + '</div>').join('')
    const h = Math.min(opts.length * 30 + 8, 248)
    const top = r.bottom + 2 + h > innerHeight ? r.top - 2 - h : r.bottom + 2
    Object.assign(box.style, { position: 'fixed', left: r.left + 'px', top: top + 'px', width: r.width + 'px', height: h + 'px', overflow: 'hidden',
      background: '#fff', border: '1px solid #94a3b8', borderRadius: '6px', boxShadow: '0 8px 24px rgba(15,23,42,.18)', padding: '4px 0',
      font: '14px/20px sans-serif', color: '#0f172a', zIndex: 2147483640 })
    document.body.appendChild(box)
    const target = box.querySelector('[data-v="' + value + '"]')
    if (!target) { box.remove(); return null }
    box.scrollTop = Math.max(0, target.offsetTop - h / 2)
    const t = target.getBoundingClientRect()
    return { x: t.left + Math.min(90, t.width / 3), y: t.top + t.height / 2 }
  }
`
async function choose(findSelectBody, value, { ms = 650 } = {}) {
  const p = await evaluate(`const el = (() => { ${findSelectBody} })(); return center(el)`)
  if (!p) { console.log('select 못 찾음'); return }
  await moveTo(p.x, p.y, ms)
  await sleep(150)   // select를 실제로 누르면 브라우저 목록 창이 열려 마우스를 가져가므로 누르는 원만 그린다
  await evaluate(`document.dispatchEvent(new MouseEvent('mousedown', { clientX: ${p.x}, clientY: ${p.y} }))`)
  await sleep(150)
  const item = await evaluate(`${LIST_JS} const el = (() => { ${findSelectBody} })(); el.focus(); return showList(el, ${JSON.stringify(String(value))})`)
  if (!item) { console.log('항목 못 찾음:', value); return }
  await sleep(450)
  await moveTo(item.x, item.y, 500)
  await sleep(300)
  await press()
  await sleep(120)
  await evaluate(`document.getElementById('demo-list')?.remove(); const el = (() => { ${findSelectBody} })(); setVal(el, ${JSON.stringify(String(value))})`)
  await sleep(450)
}
async function wheel(deltaY, steps = 12) {
  for (let i = 0; i < steps; i++) {
    await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: mx, y: my, deltaX: 0, deltaY: deltaY / steps })
    await sleep(45)
  }
}
async function key(keyName, code) {
  for (const type of ['keyDown', 'keyUp']) await send('Input.dispatchKeyEvent', { type, key: keyName, code: keyName, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code })
}

try {
  let targets
  for (let k = 0; k < 50; k++) { try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); break } catch { await sleep(200) } }
  send = await connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl)
  await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false })
  await send('Page.enable')
  await send('Page.addScriptToEvaluateOnNewDocument', { source: CURSOR_JS })
  await send('Fetch.enable', { patterns: REWRITE.map(r => ({ urlPattern: r.pattern, requestStage: 'Response' })) })
  await send('Page.navigate', { url: 'http://localhost:5173/deliveries' })
  await sleep(3500)
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: mx, y: my })
  recorder()
  await sleep(700)

  // 1) 물품 신청 목록 — 단계 칸을 한 번 훑고, 끝난 신청의 '자세히'
  mark('물품 신청 — 내 신청과 배송 단계(신청 → 준비 → 출발 → 도착 → 받음)를 한눈에 봅니다')
  await moveTo(860, 330, 900); await sleep(500)
  // 화면 위쪽에서 받음까지 끝난 첫 줄 — 번호를 박으면 신청이 늘 때 아래로 밀려 화면이 스크롤된다
  await clickAt(`const tr = [...document.querySelectorAll('tbody tr')].find(t => /\\d:\\d\\d 받음/.test(t.textContent)); return center(tr && byText('button', '자세히', tr))`, { wait: 2600 })
  mark('자세히 — 단계마다 시각과 맡은 로봇이 남습니다')
  await moveTo(mx - 160, my - 60, 900); await sleep(1600)
  await clickAt(`return center(byText('button', '닫기'))`, { wait: 900 })

  // 2) 새 물품 신청 — 즉시, 병동·품목 두 줄, 병동 하나 더 (신청은 누르지 않고 닫기)
  mark('새 신청 — 언제 보낼지(즉시·시간 지정), 목적지, 품목과 수량을 고릅니다')
  await clickAt(`return center(byText('button', '+ 요청하기'))`, { wait: 1200 })
  await clickAt(`return center(byText('button', '즉시', form()))`, { wait: 700 })
  await choose(`return form().querySelectorAll('select')[0]`, 12)          // 105호
  await choose(`return form().querySelectorAll('select')[1]`, 1)           // A 약품
  await clickAt(`return center(form().querySelectorAll('input[type=number]')[0])`, { wait: 300 })
  await key('ArrowUp', 38); await sleep(500)                               // 수량 2
  mark('+ 품목 추가 — 한 병동에 여러 품목을 함께 보냅니다')
  await clickAt(`return center(byText('button', '+ 품목 추가', form()))`, { wait: 700 })
  await choose(`return form().querySelectorAll('select')[2]`, 7)           // 환자복
  mark('+ 병동 추가 — 여러 병동을 한 번에 신청하고, 병동마다 배송이 한 건씩 생깁니다')
  await clickAt(`return center(byText('button', '+ 병동 추가', form()))`, { wait: 900 })
  await choose(`return form().querySelectorAll('select')[3]`, 20)          // 103호
  await choose(`return form().querySelectorAll('select')[4]`, 3)           // C 약품
  mark('신청하면 FMS가 로봇을 정하고, 약제실 로봇팔(OMX)이 물품을 싣습니다')
  await hoverAt(`return center([...form().querySelectorAll('button')].find(b => /신청$/.test(b.textContent.trim())))`, { wait: 1800 })   // 신청 버튼 위에만
  await wheel(-900, 14); await sleep(300)
  await clickAt(`return center(byText('button', '닫기'))`, { wait: 1200 })   // 위쪽 '닫기' — 폼을 닫음 (신청 안 함)

  // 3) 병원 지도 — 실시간 로봇 위치, 아래 로봇 카드
  mark('병원 지도 — FMS가 1초마다 보내는 로봇 위치를 지도에 그립니다')
  await clickAt(`return center(byText('aside a', '병원 지도'))`, { wait: 2800 })
  await moveTo(700, 380, 1000); await sleep(800)
  await moveTo(900, 330, 900); await sleep(1500)
  await wheel(700, 16); await sleep(600)
  const card = await evaluate(`const els = [...document.querySelectorAll('div')].filter(d => /피로도/.test(d.textContent) && d.children.length < 12 && d.getBoundingClientRect().width < 500)
    return els.length ? center(els[els.length - 1]) : null`)
  mark('로봇 카드 — 지금 있는 곳, 피로도·오염도(FMS 계산값)')
  if (card) { await moveTo(card.x - 260, card.y, 900); await sleep(900); await moveTo(card.x + 260, card.y, 1400); await sleep(1400) }
  await wheel(-700, 14); await sleep(500)

  // 4) 배송 기록 — 신청마다 단계 시각
  mark('배송 기록 — 신청·준비·출발·도착·받음을 시간 순서로 남기고 거를 수 있습니다')
  await clickAt(`return center(byText('aside a', '배송 기록'))`, { wait: 2500 })
  await moveTo(760, 330, 900); await sleep(700)
  await moveTo(760, 520, 1200); await sleep(700)
  await wheel(500, 12); await sleep(1200)
  await wheel(-500, 10); await sleep(400)

  // 5) 다시 물품 신청 목록
  mark('EMR — 신청부터 받음까지, 로봇 배송을 한 화면에서')
  await clickAt(`return center(byText('aside a', '물품 신청'))`, { wait: 1800 })
  await moveTo(900, 300, 900); await sleep(1200)
} catch (e) { console.error(e) } finally {
  recording = false
  await sleep(300)
  console.log('frames', frame)
  writeFileSync(join(dir, 'captions.json'), JSON.stringify({ fps: FPS, frames: frame, captions }, null, 1))
  chrome.kill('SIGKILL')
}
