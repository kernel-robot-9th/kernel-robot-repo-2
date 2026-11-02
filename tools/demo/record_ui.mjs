// 데모 영상 녹화기 (2026-11-02, 10-30 실물 시험의 녹화기를 옮김) — 두 화면(병원 지도 · 물품 신청)을 찍으면서 신청 화면을 직접 조작한다.
// COMMANDS 파일(줄마다 {"wards": [[장소 id, 비품 id, 개수], …]})을 읽어 '+ 요청하기 → 즉시 → 병동·물품 → 신청'을 한 틱에 한 걸음씩.
// 도착 창이 RECEIVE_AFTER_MS(기본 6초) 보이면 신청 화면에서 '받았습니다', 지도 화면의 같은 창은 '닫기'. 한 일은 ACTIONS 파일에 남긴다. STOP 파일이 생기면 끝.
// env NO_SUBMIT=1이면 '신청'을 누르지 않고 폼을 닫는다(시험 녹화 — FMS·로봇에 아무것도 가지 않음).
// node record_ui.mjs <frames_dir> <caption_file> <stop_file> <commands_file> <actions_file>   (env TOKEN, INTERVAL_MS, NO_SUBMIT, RECEIVE_AFTER_MS)
// 실제 Pinky·OMX를 부르지 않는다 — EMR 화면만 누른다. 신청이 들어가면 그다음은 EMR → FMS·OMX가 한다
import { spawn } from 'node:child_process'
import { writeFileSync, readFileSync, existsSync, mkdirSync, mkdtempSync, appendFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const [dir, captionFile, stopFile, commandsFile, actionsFile] = process.argv.slice(2)
mkdirSync(dir, { recursive: true })
// 화면마다 브라우저를 따로 — 한 브라우저의 뒤 탭은 숨은 화면이라 지도가 1초 갱신을 멈춘다
const chromes = [9334, 9336].map(port => ({ port, proc: spawn('google-chrome', ['--headless=new', `--remote-debugging-port=${port}`, '--window-size=1000,1000',
  `--user-data-dir=${mkdtempSync(join(tmpdir(), 'cdp-'))}`, '--no-first-run', 'about:blank'], { stdio: 'ignore' }) }))
const sleep = ms => new Promise(r => setTimeout(r, ms))

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl)
  await new Promise(r => ws.addEventListener('open', r, { once: true }))
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } })
  return (method, params = {}) => new Promise(r => { const n = ++id; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })) })
}

// 페이지 안에서 쓰는 도우미: 글자로 버튼 찾기, React 입력 값 바꾸기
const HELPERS = `
  const btn = (text, root = document) => [...root.querySelectorAll('button')].find(b => b.textContent.trim() === text || b.textContent.trim().startsWith(text))
  const setVal = (el, v) => { const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, String(v)); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })) }
  const form = () => [...document.querySelectorAll('h2')].find(h => h.textContent.trim() === '새 물품 신청')?.parentElement
`
const evaluate = async (page, body) => (await page.send('Runtime.evaluate', { expression: `(() => { ${HELPERS} ${body} })()`, returnByValue: true })).result?.result?.value
const log = text => { appendFileSync(actionsFile, `${new Date().toTimeString().slice(0, 8)} ${text}\n`); console.log(text) }

// 신청 한 건 = 걸음 4개 (한 틱에 하나 — 녹화에 보이게)
function orderSteps(wards) {
  return [
    ['+ 요청하기 → 즉시', `if (!form()) btn('+ 요청하기')?.click(); return 'open'`],
    ['즉시 · 병동 추가', `const f = form(); if (!f) return 'no-form'; btn('즉시', f)?.click();
      for (let i = 1; i < ${wards.length}; i++) btn('+ 병동 추가', f)?.click(); return 'ok'`],
    ['병동·물품 고르기', `const f = form(); const selects = [...f.querySelectorAll('select')]; const nums = [...f.querySelectorAll('input[type=number]')]
      const wards = ${JSON.stringify(wards)}; if (selects.length < wards.length * 2) return 'selects ' + selects.length
      wards.forEach(([loc, sup, qty], i) => { setVal(selects[i * 2], loc); setVal(selects[i * 2 + 1], sup); setVal(nums[i], qty) }); return 'ok'`],
    process.env.NO_SUBMIT === '1'
      ? ['신청 안 누름(시험) — 폼 닫기', `const f = form(); const b = [...f.querySelectorAll('button')].find(x => /신청$/.test(x.textContent.trim()))
          if (!b || b.disabled) return 'submit-disabled'; btn('닫기')?.click(); return 'ok'`]
      : ['신청 누름', `const f = form(); const b = [...f.querySelectorAll('button')].find(x => /신청$/.test(x.textContent.trim()))
          if (!b || b.disabled) return 'submit-disabled'; b.click(); return 'ok'`],
  ]
}

try {
  const pages = []
  for (const [i, path] of ['/map', '/deliveries'].entries()) {
    const { port } = chromes[i]
    let targets
    for (let k = 0; k < 50; k++) {
      try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break } catch { await sleep(200) }
    }
    const send = await connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl)
    await send('Emulation.setDeviceMetricsOverride', { width: 1000, height: 1000, deviceScaleFactor: 1, mobile: false })
    await send('Page.navigate', { url: 'http://localhost:5173/login' })
    await sleep(1500)
    await send('Runtime.evaluate', { expression: `localStorage.setItem('emr_token', ${JSON.stringify(process.env.TOKEN)})` })
    await send('Page.navigate', { url: `http://localhost:5173${path}` })
    pages.push({ path, send })
  }
  await sleep(4000)
  // 지도 화면: 지도 아래 카드가 보이게 조금 내린다
  await pages[0].send('Runtime.evaluate', { expression: 'window.scrollTo(0, 60)' })

  const start = Date.now()
  let n = 0
  let doneCommands = 0
  let steps = []
  let modalSince = null
  while (!existsSync(stopFile)) {
    const t0 = Date.now()
    const caption = existsSync(captionFile) ? readFileSync(captionFile, 'utf8').trim() : ''
    const secs = Math.floor((Date.now() - start) / 1000)
    const clock = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`
    const expr = `(() => { let d = document.getElementById('rec-caption'); if (!d) { d = document.createElement('div'); d.id = 'rec-caption';
      d.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;background:rgba(15,23,42,.92);color:#fff;font:600 22px/1.45 sans-serif;padding:14px 20px;white-space:pre-line';
      document.body.appendChild(d) } d.textContent = ${JSON.stringify(caption)} + '\\n실제 경과 ' + ${JSON.stringify(clock)} })()`
    await pages[1].send('Runtime.evaluate', { expression: expr })

    // 화면 조작: 새 명령 → 걸음, 도착 창 → 받았습니다
    if (steps.length === 0 && existsSync(commandsFile)) {
      const lines = readFileSync(commandsFile, 'utf8').split('\n').filter(Boolean)
      if (lines.length > doneCommands) {
        const { wards } = JSON.parse(lines[doneCommands])
        doneCommands += 1
        steps = orderSteps(wards)
        log(`명령 ${doneCommands}: ${JSON.stringify(wards)}`)
      }
    }
    const receiptButton = await evaluate(pages[1], `return !!btn('받았습니다')`)
    if (receiptButton) {
      modalSince ??= Date.now()
      if (Date.now() - modalSince >= Number(process.env.RECEIVE_AFTER_MS ?? 6000)) {
        const which = await evaluate(pages[1], `const t = [...document.querySelectorAll('p')].map(p => p.textContent).find(x => /^#\\d+/.test(x)); btn('받았습니다').click(); return t ?? ''`)
        log(`받았습니다 누름 ${which}`)
        modalSince = null
      }
    } else {
      modalSince = null
      if (steps.length > 0) {
        const [label, body] = steps.shift()
        const result = await evaluate(pages[1], body)
        log(`  ${label}: ${result}`)
        if (result !== 'ok' && result !== 'open') { log(`  실패 — 이 명령을 건너뜀`); steps = [] }
      }
    }
    // 지도 화면의 도착 창은 신청 화면에서 받은 뒤 닫는다
    await evaluate(pages[0], `const b = btn('받았습니다'); if (b && !${receiptButton}) btn('닫기')?.click(); return 0`)
    n += 1
    const name = String(n).padStart(5, '0')
    const shots = await Promise.all(pages.map(p => p.send('Page.captureScreenshot', { format: 'jpeg', quality: 85 })))
    writeFileSync(join(dir, `a_${name}.jpg`), Buffer.from(shots[0].result.data, 'base64'))
    writeFileSync(join(dir, `b_${name}.jpg`), Buffer.from(shots[1].result.data, 'base64'))
    await sleep(Math.max(0, Number(process.env.INTERVAL_MS ?? 500) - (Date.now() - t0)))
  }
  console.log(`frames ${n}`)
} finally {
  for (const c of chromes) c.proc.kill()
}
