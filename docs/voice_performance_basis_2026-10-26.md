# 음성 성능 비교 — 근거와 방법 (2026-10-26 조사, 비교는 다음 작업)

- 대상: 음성 기능을 이어서 작업할 팀원·Claude. EMR 음성 기능(**`/api/v2/voice`** — 말로 예약 `/voice/parse`·`/voice/parse-text`, 안내 음성 `POST /voice/speak`, 브라우저 안내 음성. 10-26 측정 뒤 v1에서 v2로 옮김, 고도화는 v2에서)의 **속도·품질을 무엇과 어떻게 비교할지** 근거를 모은 문서다.
- 계기: `/voice/speak`에서 새 문장의 첫 소리가 나오기까지 **5.7~7.9초** 걸린다. 사용자가 "API라서 전송·출력 속도가 있지 — 수치화하고 무엇과 비교할지" 물었다.
- 이 문서는 조사와 오늘 실측만 담았다. 후보 설치·비교 측정은 하지 않았다(3장이 다음 작업 계획).
- 기능 설명은 [`architecture/README.md`](architecture/README.md) 4.14, 결정 사항은 `emr/CLAUDE.md` "음성 배송 예약".

## 1. 오늘 실측 (이 서버, 2026-10-26, 각 2회)

측정 환경:
- 서버: `fastcamp1-OMEN`, EMR api 컨테이너
- 안내 음성 API: Gemini TTS `gemini-3.8-flash-tts`, 목소리 Kore, 비스트리밍
- 브라우저 목소리: headless Chrome의 speechSynthesis

**사건 → 첫 소리까지**

| 문장 (글자 / 음성 길이) | Gemini TTS API (새 문장) | 같은 API (캐시) | 브라우저 "Google 한국의" | 로컬 espeak-ng (브라우저 경유) |
|---|---|---|---|---|
| 짧음 14자 / 2.7초 | 5.70~5.72초 | — | 0.44~0.57초 | 0.07~0.11초 |
| 보통 46자 / 8.6초 | 6.46~6.79초 | **0.007초** | 0.32~0.33초 | 0.06~0.07초 |
| 김 76자 / 13.4초 | 6.87~7.93초 | — | 0.32~0.49초 | 0.05~0.06초 |

시간이 어디서 드는지:
- **Gemini 쪽**: 서버 로그 `voice_speech_made.elapsed_ms`로 본 Gemini 호출이 5,683~7,925ms다. 지연은 거의 전부 여기서 난다.
- **EMR 서버 처리**: API 전체 시간에서 Gemini 시간을 뺀 값이 10~34ms다.
- **전송**: WAV 135~645KB(24kHz 모노 16비트). 100Mbps LAN에서 최대 약 50ms, 같은 PC에서는 무시할 수준이다.
- **모형**: 지연 ≈ 고정 약 5.3초 + 글자당 약 0.027초. 짧은 안내일수록 손해다.
- **실시간 계수**(RTF = 합성 시간 ÷ 음성 길이, 1보다 작으면 실시간보다 빠름): 짧음 2.1, 보통 0.77, 김 0.55.

음성 인식(STT, Gemini `gemini-3.8-flash`, 받아 적기 + 추출 1회):
- 문장 입력: 6.0~7.0초
- 녹음 4.3초 분량: 6.6초

측정 한계:
- 브라우저 목소리는 **headless(스피커 없음)**에서 `speak()` → `onstart`·`onend` 이벤트로만 쟀다. 실제 스피커로는 조금 다를 수 있다.
- "Google 한국의"는 **인터넷이 필요한** 목소리다. 목소리 종류는 기기·OS마다 다르다.
- 2회씩만 쟀다. 다음 비교는 웜업 1회를 버리고 5회 이상 잰다.

## 2. 근거 (조사)

### 2.1 지표 정의
- **TTFA**(time to first audio, 첫 소리까지): 요청을 보낸 뒤 재생할 수 있는 첫 오디오 조각을 받기까지의 시간. 전체 합성 시간과는 따로 본다. 스트리밍이면 이 값이 크게 줄어든다.
  - [Gradium — TTS Latency Benchmark 2026](https://gradium.ai/content/tts-latency-benchmark-2026), [Gradium — Best Low-Latency TTS APIs 2026](https://gradium.ai/content/best-low-latency-tts-apis-2026)
- **RTF**: 문서마다 방향이 반대다. 합성 시간 ÷ 음성 길이(작을수록 좋음)로 쓰기도 하고, 음성 길이 ÷ 합성 시간(클수록 좋음)으로 쓰기도 한다. **이 저장소는 합성 시간 ÷ 음성 길이로 쓴다.**
  - [Smallest AI — Metrics Overview](https://docs.smallest.ai/models/documentation/text-to-speech-lightning/benchmarks/metrics-overview)
- 업체 수치는 측정 조건(동시 요청 수·지역·오디오 형식)이 붙어 있어 그대로 비교하면 안 된다. 같은 조건으로 직접 잰다.

### 2.2 허용 기준 — "얼마나 빨라야 하나"
- **Nielsen의 응답 시간 세 한계**(1993, Miller 1968에서 유래):
  - 0.1초: 즉시로 느낀다.
  - **1초: 생각의 흐름이 끊기지 않는다(지연은 느낌).**
  - 10초: 주의를 붙잡는 한계. 넘으면 진행 표시가 필요하다.
  - [NN/g — The 3 Response Time Limits](https://www.nngroup.com/videos/3-response-time-limits-interaction-design/)
- **대화형 음성 업계 목표**: TTFA 약 200~300ms.
  - 상용 TTS API 중앙값 155~313ms(Gradium·Cartesia·ElevenLabs·Deepgram — Gemini는 없음, 업체 발표라 참고만): [Gradium 벤치마크](https://gradium.ai/content/tts-latency-benchmark-2026)
- **제안 목표(안내 방송)**: 사건(도착 등) → 첫 소리 **1초 이하**.
  - 대화가 아니라 일방 안내라 200~300ms까지는 필요 없다.
  - 지금 Gemini 새 문장(5.7~7.9초)은 이 기준을 넘는다. 캐시(0.007초)와 브라우저 내장(0.3~0.6초)은 기준 안이다.

### 2.3 Gemini TTS 지연에 대해 알려진 것
- 공식 지연 수치는 찾지 못했다. 그래서 **우리 실측이 근거**다.
- 개발자 포럼 보고(Gemini 3.1 Flash TTS 미리보기):
  - 같은 문장이 AI Studio 기본 키로는 2초 미만, 개인 API 키로는 첫 조각까지 10~20초였다.
  - 작성자는 모델보다 라우팅·용량 문제로 봤고, 스트리밍 조기 종료 버그도 언급됐다.
  - [Google AI Developers Forum — 3.1 flash TTS preview streaming latency](https://discuss.ai.google.dev/t/3-1-flash-tts-preview-streaming-latency/176050)
- 시사점:
  - 지연이 **키·시간대에 따라 들쭉날쭉**할 수 있다 → 비교 때 시간대를 나눠 두 번 잰다.
  - **스트리밍**이면 첫 소리가 빨라질 수 있다 → 후보에 넣는다. 지원 여부와 조기 종료 버그를 확인한다.
  - 참고: [Gemini Streaming TTS (Towards AI)](https://pub.towardsai.net/gemini-streaming-tts-how-developers-can-make-ai-voice-apps-feel-instant-01ef246f398e)

### 2.4 품질 지표 — 속도만 비교하면 espeak가 이긴다
- **명료도(알아듣기) — ASR 왕복 CER**:
  - 방법: 만든 음성을 음성 인식기로 다시 받아 적어 원문과 문자 오류율(CER)을 비교한다. 한국어는 단어보다 글자 단위(CER)가 맞다.
  - **인식기를 바꾸면 수치가 바뀐다** → 모든 후보에 같은 인식기 하나를 쓴다.
  - 문장부호·띄어쓰기 정규화 규칙도 미리 정한다(정규화에 따라 수치가 달라진다).
  - [CTC-TTS (arXiv 2602.19574)](https://arxiv.org/pdf/2602.19574) — whisper-large-v3로 WER·CER, [Alphacephei — Russian TTS 평가](https://alphacephei.com/nsh/2024/07/12/russian-tts.html)
- **자연스러움 — MOS**:
  - ITU-T P.800 ACR. 듣는 사람이 샘플마다 5 아주 좋음 · 4 좋음 · 3 보통 · 2 나쁨 · 1 아주 나쁨을 매기고 평균을 낸다.
  - 점수 간격이 같다고 볼 수 없는 서열 척도라 작은 차이는 의미가 적다.
  - UTMOS 같은 자동 예측 MOS는 보조로만 쓴다.
  - [Mean opinion score (Wikipedia)](https://en.wikipedia.org/wiki/Mean_opinion_score), [Picovoice — Measuring TTS quality](https://picovoice.ai/blog/measuring-tts-quality/), [Audio evaluation metrics 개요](https://learn.traeai.com/t/ai-engineering/phases/06-speech-and-audio/17-audio-evaluation-metrics)

### 2.5 로컬 한국어 TTS 후보 (데이터가 PC 밖으로 안 나감)
이 PC: RTX 5080 Laptop 16GB(사용 약 0.9GB), torch 2.14 + CUDA 13, RAM 15GB(여유 약 3GB, 10-26 측정).

| 후보 | 한국어 | 라이선스 | 알려진 것 | 확인할 것 |
|---|---|---|---|---|
| **MeloTTS-Korean** | 있음 | MIT | VITS·VITS2·Bert-VITS2 기반. "CPU에서 준실시간·GPU 약 0.5GB"는 2차 자료 | 실제 TTFA·RTF·발음(숫자·영문 "A 약품") — [HF](https://huggingface.co/myshell-ai/MeloTTS-Korean) |
| **Supertonic 3** | 있음(31개 언어) | 가중치 BigScience OpenRAIL-M(용도 제한), 코드 MIT | ONNX Runtime·기기 안 실행·약 99M 파라미터. 속도표는 업체 발표 | ⚠️ 회사 해산 주장(제3자 미러 README, **미확인**) → 장기 지원·가중치 배포 위험. [HF supertonic-2](https://huggingface.co/Supertone/supertonic-2), [GitHub](https://github.com/supertone-inc/supertonic) |
| XTTS-v2 | 이번 조사로 확인 못 함 | 확인 필요 | — | 한국어 지원·라이선스(상업 이용) |
| espeak-ng | 있음(이 PC에 설치됨) | GPL | 첫 소리 0.05~0.1초, 기계음 | 하한 기준선으로만 |

비교표·순위 사이트([Clore.ai TTS 비교](https://docs.clore.ai/guides/guides_v2-es/comparaciones/tts-comparison) 등)는 한국어 측정이 없거나 표가 잘려 있어 근거로 쓰지 않았다. GPU 임대 업체의 RTF 수치도 같은 이유로 제외했다.

## 3. 다음 비교 방법 (제안)

**후보** (같은 문장 묶음, 같은 PC):
1. Gemini TTS 비스트리밍 — 지금 `/voice/speak`
2. Gemini TTS 스트리밍 — 첫 조각까지
3. **캐시 미리 채우기** — 안내 문장 템플릿 × 장소를 서버 시작 때 만들어 둠. 템플릿 3~4개 × 장소 12곳 ≈ 50문장, 지금 캐시 크기 64 안
4. 브라우저 내장 — Google 한국의 / OS 목소리
5. MeloTTS-Korean — 로컬 GPU
6. Supertonic 3 — 로컬 ONNX
7. espeak-ng — 하한 기준선

**문장 묶음** (모든 후보 같은 것):
- 실제 안내 10개 정도: 출발·도착("받았습니다를 눌러 주세요")·실패·통행 안내
- 장소 이름 12곳, 짧음·보통·김을 섞는다
- 숫자·영문이 든 것도 넣는다("A 약품 2개", "1인실 가운데 위-왼")

**지표**

| 지표 | 정의 | 목표·판정 |
|---|---|---|
| TTFA | 요청 → 첫 소리, 중앙값·p95 | ≤ 1초 |
| RTF | 합성 시간 ÷ 음성 길이 | < 1 |
| CER | 같은 STT로 받아 적어 원문과 비교 | 낮을수록 좋음, 숫자·장소 이름 오류는 따로 셈 |
| MOS | 팀원 3명 이상, 1~5점, 후보 이름을 가리고 섞어 들려줌 | 높을수록 좋음 |
| 운영 | GPU·RAM 사용, 오프라인 동작, 라이선스, 데이터가 밖으로 나가는지, 비용 | 표로 정리 |

**측정 규칙**:
- 웜업 1회는 버리고 5회 잰다.
- Gemini는 오전·오후 두 번 잰다(2.3절의 변동 때문).
- **설치**: 로컬 TTS는 EMR api 컨테이너가 아니라 별도 conda 환경에 둔다. 메모리가 15GB라 측정 중에는 Ollama·불필요한 컨테이너를 확인한다(루트 CLAUDE.md 규칙 6).
- **CER용 STT**: 하나로 고정한다 — Gemini STT(이미 연결됨) 또는 로컬 faster-whisper(데이터가 안 나감). 고른 이유를 결과 문서에 적는다.
- **결과**: 이 폴더에 `voice_performance_comparison_<날짜>.md`로 표 + 결론 + 추천(지금 `/voice/speak` 엔진을 바꿀지, 캐시만 미리 채울지).

## 부록 — 오늘 원자료

`POST /voice/speak` (urllib, 같은 PC, 끝 공백으로 캐시 회피):
```
짧음 14자: first_byte 5716 / 5697 ms, audio 2.76 / 2.72 s, 135 / 133 KB
보통 46자: first_byte 6790 / 6457 ms, audio 8.68 / 8.60 s, 413 / 409 KB
김   76자: first_byte 6869 / 7932 ms, audio 13.24 / 13.64 s, 627 / 645 KB
보통(캐시): first_byte 6 ms, total 7 ms
서버 로그 Gemini elapsed_ms: 5683 · 5689 · 6782 · 6448 · 6860 · 7925
```
브라우저 speechSynthesis (headless Chrome, `speak()` → `onstart` / `onend`, ms):
```
Google 한국의   짧음 567/2832, 444/2535 · 보통 326/6803, 315/6779 · 김 492/10704, 324/10531
Korean espeak-ng 짧음 111/2894,  69/2824 · 보통  56/7527,  68/7559 · 김  56/11794,  54/11773
```
문장:
- 짧음 "배송 로봇이 출발했습니다."
- 보통 "4인실 왼쪽에 배송 로봇이 도착했습니다. 물건을 받은 뒤 받았습니다를 눌러 주세요."
- 김 "안내 말씀 드립니다. 수술실로 가는 배송 로봇이 복도를 지나갑니다. 통로를 비워 주시고, 로봇 앞을 가로지르지 말아 주세요. 감사합니다."
