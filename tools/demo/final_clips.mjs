// 최종 영상용 짧은 영상 2편 + 화면 5장 (2026-11-03). tools/demo/intro_cursor.mjs의 커서·목록·응답 고치기를 그대로 씀.
//   request <frames_dir>        배송 요청: + 요청하기 → 시간 지정(SCHEDULE, 앞으로의 시각) → 105호 · A 약품 → 신청
//   receive <frames_dir> <id>   배송 받음: 목록을 연 채 FMS 'order_delivered'를 EMR에 직접 보냄(가상 도착) → 도착 창 → 받았습니다
//                               ⚠️ 그 배송의 fms_orders를 미리 채워 둬야 한다(EMR이 실제 FMS로 주문을 보내지 않게)
//   shots <out_dir>             화면 5장 (02는 receive가 찍음)
// 녹화 브라우저에서만: 신청 목록의 취소된 줄 숨김, 지도 로봇은 연결됨·대기
import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const [mode, dir, arg] = process.argv.slice(2)
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
let t0 = Date.now()
const captions = []   // [{ t: 녹화 시작부터 초, text }]
const mark = text => captions.push({ t: (Date.now() - t0) / 1000, text })
async function recorder() {
  t0 = Date.now(); captions.length = 0
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

const waitFor = async (body, ms = 15000) => {
  for (const end = Date.now() + ms; Date.now() < end; await sleep(200)) if (await evaluate(body)) return true
  return false
}
const shot = async path => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(path, Buffer.from(r.result.data, 'base64'))
  console.log('찍음', path)
}
async function open(path, { record = true } = {}) {
  await send('Page.navigate', { url: 'http://localhost:5173' + path })
  await sleep(3500)
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: mx, y: my })
  if (record) recorder()
}

try {
  let targets
  for (let k = 0; k < 50; k++) { try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); break } catch { await sleep(200) } }
  send = await connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl)
  await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false })
  await send('Page.enable')
  await send('Page.addScriptToEvaluateOnNewDocument', { source: CURSOR_JS })
  await send('Fetch.enable', { patterns: REWRITE.map(r => ({ urlPattern: r.pattern, requestStage: 'Response' })) })

  if (mode === 'request') {
    await open('/deliveries'); await sleep(600)
    mark('새 배송 요청 — 보낼 시간, 병실, 약품을 고릅니다')
    await clickAt(`return center(byText('button', '+ 요청하기'))`, { wait: 900 })
    await clickAt(`return center(byText('button', '시간 지정', form()))`, { wait: 500 })
    const p = await evaluate(`return center(form().querySelector('input[type="datetime-local"]'))`)
    await moveTo(p.x, p.y, 500); await press(); await sleep(300)
    await evaluate(`setVal(form().querySelector('input[type="datetime-local"]'), ${JSON.stringify(process.env.SCHEDULE)})`)
    await sleep(500)
    await choose(`return form().querySelectorAll('select')[0]`, process.env.ROOM_ID)
    await choose(`return form().querySelectorAll('select')[1]`, process.env.SUPPLY_ID)
    mark('신청 — 정한 시간이 되면 FMS가 로봇을 보냅니다')
    await clickAt(`return center([...form().querySelectorAll('button')].find(b => /신청$/.test(b.textContent.trim())))`, { wait: 1200 })
    await waitFor(`return !form()`)
    const created = await evaluate(`const tr = [...document.querySelectorAll('tbody tr')].sort((a, b) => +b.cells[0].textContent - +a.cells[0].textContent)[0]
      return tr && { id: +tr.cells[0].textContent, at: center(tr.cells[4]) }`)
    console.log('CREATED', created?.id)
    if (created) { await moveTo(created.at.x, created.at.y, 700) }
    await sleep(1800)
  } else if (mode === 'receive') {
    await open('/deliveries'); await sleep(800)
    mark('로봇이 병실에 도착하면 신청한 간호사 화면에 창이 뜹니다')
    // 가상 도착 — FMS가 보내는 것과 같은 이벤트를 EMR에 직접
    const res = await fetch('http://localhost:8000/api/v1/fms/events', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: `demo-${arg}`, seq: 0, time: new Date().toISOString(), type: 'order_delivered', order_id: `demo-${arg}-1`, robot: 1 }) })
    console.log('event', res.status, await res.text())
    if (!await waitFor(`return !!byText('button', '받았습니다', document.querySelector('[role=dialog]') || document)`)) throw new Error('도착 창이 안 뜸')
    await sleep(1600)
    await shot(join(dir, '..', '02_arrived_received_button.png'))
    mark('물건을 받고 "받았습니다"를 누르면 수령이 끝납니다')
    const big = await evaluate(`const bs = [...document.querySelectorAll('button')].filter(b => b.textContent.trim() === '받았습니다')
      const b = bs.sort((x, y) => y.getBoundingClientRect().height - x.getBoundingClientRect().height)[0]; return center(b)`)
    await moveTo(big.x, big.y, 900); await sleep(400); await press()
    await waitFor(`const tr = [...document.querySelectorAll('tbody tr')].find(t => t.cells[0].textContent.trim() === '${arg}'); return tr && /받음/.test(tr.textContent) && /\\d:\\d\\d 받음/.test(tr.textContent)`)
    mark('배송 단계가 받음까지 채워집니다')
    const row = await evaluate(`const tr = [...document.querySelectorAll('tbody tr')].find(t => t.cells[0].textContent.trim() === '${arg}'); return center(tr && tr.cells[4])`)
    if (row) await moveTo(row.x, row.y, 800)
    await sleep(2000)
  } else if (mode === 'shots') {
    recording = false
    await open('/deliveries', { record: false }); await sleep(1500)
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 1279, y: 799 })
    await evaluate(`document.getElementById('demo-cursor')?.remove()`)
    await shot(join(dir, '01_deliveries.png'))
    await open('/map', { record: false }); await sleep(2500); await evaluate(`document.getElementById('demo-cursor')?.remove()`)
    await shot(join(dir, '03_map.png'))
    await open('/delivery-log', { record: false }); await sleep(2000); await evaluate(`document.getElementById('demo-cursor')?.remove()`)
    await shot(join(dir, '05_delivery_log.png'))
    if (process.env.BEDSIDE_KEY) {
      await evaluate(`localStorage.setItem('emr_bedside_key', ${JSON.stringify(process.env.BEDSIDE_KEY)}); return true`)
      await open('/bedside', { record: false }); await sleep(2500)
      // 환자가 고르는 모습 — 첫 품목 +1
      await evaluate(`const plus = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '+'); plus && plus.click(); return true`)
      await sleep(500); await evaluate(`document.getElementById('demo-cursor')?.remove(); localStorage.removeItem('emr_bedside_key')`)
      await shot(join(dir, '04_bedside.png'))
    }
  }
} catch (e) { console.error(e) } finally {
  recording = false
  await sleep(300)
  console.log('frames', frame)
  if (mode !== 'shots') writeFileSync(join(dir, 'captions.json'), JSON.stringify({ fps: FPS, frames: frame, captions }, null, 1))
  chrome.kill('SIGKILL')
}
