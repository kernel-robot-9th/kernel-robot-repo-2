// EMR 배송 웹페이지 기능 소개 영상 (2026-11-02 사용자: 자막 없이, 배송 기준 웹페이지 소개 하나, 마우스 커서 보이게).
// 실제 마우스 이벤트(CDP Input)로 움직이고 누른다. 화면에 커서 그림을 얹어 마우스를 따라가게 한다.
// ⚠️ '신청'은 누르지 않는다 — 누르면 FMS 주문이 나가 실제 Pinky가 움직인다. 폼은 채운 뒤 '닫기'.
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
  ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } })
  return (method, params = {}) => new Promise(r => { const n = ++id; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })) })
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
// select는 실제로 누르면 목록 창이 따로 떠서 녹화에 안 보인다 → 커서로 누르는 시늉(원) + 값만 바꿈
async function choose(findSelectBody, value, { ms = 650 } = {}) {
  const p = await evaluate(`const el = (() => { ${findSelectBody} })(); return center(el)`)
  if (!p) { console.log('select 못 찾음'); return }
  await moveTo(p.x, p.y, ms)
  await sleep(200)
  await evaluate(`const el = (() => { ${findSelectBody} })(); document.dispatchEvent(new MouseEvent('mousedown', { clientX: ${p.x}, clientY: ${p.y} })); el.focus()`)
  await sleep(450)
  await evaluate(`const el = (() => { ${findSelectBody} })(); setVal(el, ${JSON.stringify(String(value))})`)
  await sleep(500)
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
  await send('Page.navigate', { url: 'http://localhost:5173/deliveries' })
  await sleep(3500)
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: mx, y: my })
  recorder()
  await sleep(1500)

  // 1) 물품 신청 목록 — 단계 칸을 훑고, 끝난 신청의 '자세히'
  await moveTo(640, 300, 900); await sleep(400)
  await moveTo(820, 340, 900); await sleep(400)
  await moveTo(820, 420, 700); await sleep(500)
  await clickAt(`const tr = row(380); return center(tr && byText('button', '자세히', tr))`, { wait: 2600 })
  await moveTo(mx - 160, my - 60, 900); await sleep(1600)
  await clickAt(`return center(byText('button', '닫기'))`, { wait: 900 })

  // 2) 새 물품 신청 — 즉시, 병동·품목 두 줄, 병동 하나 더 (신청은 누르지 않고 닫기)
  await clickAt(`return center(byText('button', '+ 요청하기'))`, { wait: 1200 })
  await clickAt(`return center(byText('button', '즉시', form()))`, { wait: 700 })
  await choose(`return form().querySelectorAll('select')[0]`, 12)          // 105호
  await choose(`return form().querySelectorAll('select')[1]`, 1)           // A 약품
  await clickAt(`return center(form().querySelectorAll('input[type=number]')[0])`, { wait: 300 })
  await key('ArrowUp', 38); await sleep(500)                               // 수량 2
  await clickAt(`return center(byText('button', '+ 품목 추가', form()))`, { wait: 700 })
  await choose(`return form().querySelectorAll('select')[2]`, 7)           // 환자복
  await clickAt(`return center(byText('button', '+ 병동 추가', form()))`, { wait: 900 })
  await choose(`return form().querySelectorAll('select')[3]`, 20)          // 103호
  await choose(`return form().querySelectorAll('select')[4]`, 3)           // C 약품
  await hoverAt(`return center([...form().querySelectorAll('button')].find(b => /신청$/.test(b.textContent.trim())))`, { wait: 1800 })   // 신청 버튼 위에만
  await wheel(-900, 14); await sleep(300)
  await clickAt(`return center(byText('button', '닫기'))`, { wait: 1200 })   // 위쪽 '닫기' — 폼을 닫음 (신청 안 함)

  // 3) 병원 지도 — 실시간 로봇 위치, 아래 로봇 카드
  await clickAt(`return center(byText('aside a', '병원 지도'))`, { wait: 2800 })
  await moveTo(700, 380, 1000); await sleep(800)
  await moveTo(900, 330, 900); await sleep(1500)
  await wheel(700, 16); await sleep(600)
  const card = await evaluate(`const els = [...document.querySelectorAll('div')].filter(d => /피로도/.test(d.textContent) && d.children.length < 12 && d.getBoundingClientRect().width < 500)
    return els.length ? center(els[els.length - 1]) : null`)
  if (card) { await moveTo(card.x - 260, card.y, 900); await sleep(900); await moveTo(card.x + 260, card.y, 1400); await sleep(1400) }
  await wheel(-700, 14); await sleep(500)

  // 4) 배송 기록 — 신청마다 단계 시각
  await clickAt(`return center(byText('aside a', '배송 기록'))`, { wait: 2500 })
  await moveTo(760, 330, 900); await sleep(700)
  await moveTo(760, 520, 1200); await sleep(700)
  await wheel(500, 12); await sleep(1200)
  await wheel(-500, 10); await sleep(400)

  // 5) 다시 물품 신청 목록
  await clickAt(`return center(byText('aside a', '물품 신청'))`, { wait: 1800 })
  await moveTo(900, 300, 900); await sleep(2000)
} catch (e) { console.error(e) } finally {
  recording = false
  await sleep(300)
  console.log('frames', frame)
  chrome.kill('SIGKILL')
}
