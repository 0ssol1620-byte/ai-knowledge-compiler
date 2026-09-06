# TAVONEL Model Arena — 인수인계

캠페인 `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1`
작성 2026-09-04 10:40Z · 네임스페이스 `research/model_arena_20260903` (git 미추적)

이 문서 하나만 읽고 바로 이어받을 수 있게 썼다. 순서는 **지금 무엇이 돌고 있는가 →
어떻게 손대는가 → 무엇이 왜 실패했고 어떻게 고쳤는가 → 남은 일**이다.

> **가장 먼저 확인할 것**: 수퍼바이저 프로세스가 살아 있는지. 죽어 있으면 GPU 런은
> 새 pod을 못 받고 조용히 멈춘다. 확인·재기동 절차는 §2.2.

---

## 0. 이 캠페인이 지켜야 하는 규칙 (사용자 지시, 변경 금지)

트랜스크립트가 잘려도 이 여덟 줄은 살아남아야 한다.

1. Opus 테스트는 **구독 OAuth**로 한다. API 키를 쓰지 않는다.
2. **Opus → Sonnet, Opus → API 자동 전환 금지.** 못 돌면 못 돈다고 보고한다.
3. RunPod 플러그인으로 **로그도 함께 확인**한다.
4. **secret 값을 log/receipt/chat에 절대 출력하지 않는다.**
5. 사용자가 명시적으로 요청하기 전까지 **commit/push 하지 않는다.**
6. **Infinity를 벤치마크에서 제외하지 않는다.**
7. 실제 GPU inference 증거가 나오기 전에는 `RUNPOD_E2E_SMOKE`라고 보고하지 않는다.
8. 준비에서 멈추지 말고 **실제 데이터를 만든다.**

파생 운영 규칙 하나 더:

- **arena pod에 RunPod 플러그인의 `get-pod` / `list-pods`를 쓰지 마라.** 응답에 워커
  토큰이 든 env가 통째로 실린다. `stream-pod-logs`는 괜찮고, arena 자체의
  `RunPodV1Client.list_pods()`는 id/name만 찍으므로 괜찮다.
- 이 네임스페이스 밖의 파일, 더티 상태인 파일, SFIR frozen state는 건드리지 않는다.

보고 어휘는 `DESIGNED, UNIT_TESTED, PROVIDER_LIVE_READ, DRY_RUN_VALIDATED,
RUNPOD_E2E_SMOKE, CANARY_EXECUTED, FULL_RUN_EXECUTED, OUTPUT_FROZEN, SCORED,
REPORTED, CLEANED_UP` 로 제한된다.

---

## 1. 지금 상태 (2026-09-04 10:36Z 실측)

### 1.1 GPU 레인 — 11개 모델 × 5,132 페이지 = 56,452

| 모델 | 완료 | 비율 | PENDING | RUNNING | QUARANTINED | FAILED |
|---|---|---|---|---|---|---|
| `glm_ocr` | 4,218 | 82.2% | 952 | 0 | 7 | 0 |
| `unlimited_ocr` | 3,094 | 60.3% | 2,037 | 7 | 0 | 9 |
| `olmocr2` | 2,234 | 43.5% | 2,910 | 3 | 0 | 0 |
| `ovisocr2` | 2,162 | 42.1% | 2,984 | 1 | 0 | 0 |
| `monkeyocrv2_b` | 2,060 | 40.1% | 3,085 | 2 | 0 | 0 |
| `hpd_parsing` | 1,742 | 33.9% | 3,388 | 2 | 0 | 0 |
| `deepseek_ocr2` | 1,465 | 28.5% | 3,678 | 4 | 0 | 0 |
| `infinity_parser2_pro` | 1,354 | 26.4% | 3,793 | 0 | 0 | 0 |
| `mineru_pipeline` | 784 | 15.3% | 4,362 | 1 | 0 | 0 |
| `mineru_vlm` | 612 | 11.9% | 4,624 | 1 | 0 | 0 |
| `paddleocr_vl_1_6` | 473 | 9.2% | 4,658 | 1 | 0 | 0 |

**합계 20,198 / 56,452 = 35.8%.** 청구액 **$126.50**. 측정 처리율 약 3,000 페이지/시간
이므로 남은 36,000 페이지는 **약 12시간**.

`glm_ocr`의 QUARANTINED 7건은 `OUTPUT_MALFORMED`(모델이 `raw_output` 없이 응답)이다.
**의미적 실패이고 정상 종결 상태다.** 재시도 대상이 아니고, freeze를 막지도 않는다.

### 1.2 Opus 구독 레인 — 별도 진행, GPU 예산과 무관

3,226 / 5,132 = 62.9% (FAILED 47). 구독 쿼터에 묶여 있어 워커를 늘려도 빨라지지 않는다.
관측 속도로 남은 약 1,900 페이지는 **약 3시간**.

```bash
cd /d/CodexProjects/ai-knowledge-compiler/research/model_arena_20260903 && python -m arena.opus status
```

### 1.3 예산

| 항목 | 값 |
|---|---|
| 청구 완료 | $126.50 |
| 미정산 pod 예약(held) | $155.39 |
| D22 soft cap | $300 (여기서 **거부**된다) |
| D22 hard cap | $500 |
| 승인 receipt | `phase2_full_run-20260904T012000Z.json`, 액션당 최대 $60 |
| 예측 총액 | 약 $235 |

**soft cap이 실질 상한이다.** `allowed = not over_soft_cap`이고, 게이트는
`청구액 + 미정산 예약 + 이번 액션`을 본다. 예약은 pod이 정산되면 실제 금액으로 대체된다(D75).

pod 178개 중 80개만 실제로 페이지를 처리했다. 나머지 $41.23은 아래 §3의 사고들에서
나온 손실이며, 원인은 모두 제거됐다.

---

## 2. 조작 방법

### 2.1 환경

```bash
export PATH="/c/Program Files/Git/usr/bin:$PATH"
cd /d/CodexProjects/ai-knowledge-compiler/research/model_arena_20260903
export PYTHONIOENCODING=utf-8
```

인터프리터는 반드시 `D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe`.

**Bash heredoc 함정**: `python - <<'PY'` 안에서는 Bash 툴이 백슬래시를 반으로 줄인다.
`"\\n"`이 진짜 개행이 되어 파이썬 파일이 깨진다. **이스케이프가 들어가는 패치 스크립트는
반드시 Write 툴로 파일을 만들어 실행한다.**

### 2.2 수퍼바이저 — GPU 런의 심장

`scratchpad/supervise_full.py`가 슬라이스를 계속 살려 놓는다. 고정 목록이 없고, 매 90초
마다 (a) 어떤 슬라이스에 드라이버가 살아 있는지 (b) 어떤 모델에 PENDING이 남았는지를
묻고 빠진 것을 예산 한도 안에서 띄운다. **남은 페이지가 많은 모델부터** 띄운다.

살아 있는지 확인:

```bash
powershell.exe -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*supervise_full*' }).Count"
```

`2`가 정상이다(venv `python.exe`는 런처라 같은 커맨드라인으로 두 번 보인다). `0`이면 죽은 것.

상태 파일: `scratchpad/fullrun/supervisor-state.json`
로그: `scratchpad/fullrun/supervisor.log`
슬라이스별 로그: `scratchpad/fullrun/<model>-s<i>of<n>.log`

재기동:

```bash
rm -f "$SCRATCH/fullrun/SUPERVISOR_STOP" && python "$SCRATCH/supervise_full.py" >> "$SCRATCH/fullrun/supervisor.log" 2>&1 &
```

### 2.3 멈추는 법 — **여기서 돈이 샌다**

| 목적 | 방법 |
|---|---|
| 모델 하나 깨끗이 | `runs/<model>/STOP` 파일 생성. 드라이버가 처리 중 페이지를 마치고 pod을 반납한 뒤 종료 |
| 수퍼바이저만 | `Stop-Process -Id <pid> -Force` (PID 지정) |
| 새 슬라이스만 막기 | `scratchpad/fullrun/SUPERVISOR_STOP` 파일 생성 |

**절대 하지 말 것: 수퍼바이저나 드라이버에 `TaskStop`(프로세스 트리 kill).** 드라이버는
`finally` 블록에서 pod을 반납한다. 트리로 죽이면 그 블록에 도달하지 못하고 pod이 계속
과금된다. 2026-09-04 05:50Z에 이 실수로 pod 20개가 고아가 됐다(D82).

고아 pod 정리:

```bash
python -m arena.controller cleanup-verify --execute
```

그 다음 `scratchpad/settle_orphans.py`로 원장에 추정 정산 행을 써야 예약이 풀린다.

### 2.4 자주 쓰는 명령

```bash
python -m arena.controller status
python -m arena.controller run --model <m> --execute --shard-index <i> --shard-count <n> --max-pods 3 --lifetime-hours 3
python -m arena.controller freeze --model <m>
python -m arena.controller cleanup-verify --execute
python -m arena.reports.forecast
python -m arena.reports build
python -m arena.scoring qa|prepare|score --model <m> [--dry-run]
python -m arena.tavonel signals|freeze-routes|replay|plan-recovery|disagreement|cost
```

**`--execute`는 "돈을 쓴다"는 표시일 뿐, "안전하다"는 표시가 아니다.** `freeze`는 돈을
안 쓰므로 게이트가 없었고, 그래서 구경하려고 친 명령이 실제로 얼려 버렸다(§3.7).

### 2.5 테스트

테스트 디렉터리는 **따로** 돌린다. `tests/scoring`과 `tests/tavonel`을 같이 돌리면
conftest 이름이 충돌해 수집 단계에서 죽는다(기존 문제, 이번 변경과 무관).

```bash
for d in controller core provider scoring reports tavonel runtimes; do python -m pytest tests/$d -q; done
python -m ruff check . && python -m mypy arena/
```

현재 전부 통과: controller 363 · core 451(+1 skip) · provider 165 · scoring 113 ·
reports 111 · tavonel 140 · runtimes 859 = **2,202 passed**. lint/type 클린.

core의 skip 1건은 §3.6의 사고를 정직하게 기록하는 skip이다.

---

## 3. 무엇이 실패했고 어떻게 고쳤는가

계약 결정은 `ARENA_CONTRACT.md` §11.7에 D41–D88로 기록돼 있다. 여기서는 이번에 실제로
손실을 낸 것들만 **원인 → 손실 → 수정** 순으로 정리한다.

### 3.1 D80 — 여러 드라이버가 같은 모델을 동시에 plan

- **증상**: 첫 병렬 기동에서 31개 슬라이스 중 18개가 수 초 만에 죽음.
- **원인 둘**. `enqueue`가 "이 id 있나?" 확인 후 INSERT 하는 구조라 두 드라이버가
  동시에 없다고 읽고 둘 다 넣어 `UNIQUE constraint failed: jobs.inference_job_id`.
  그리고 autocommit이라 5,132건 INSERT가 각각 쓰기 락을 잡아 `database is locked`.
- **수정**: `ON CONFLICT(inference_job_id) DO NOTHING` + 배치 전체를 `BEGIN IMMEDIATE`
  한 트랜잭션으로, `busy_timeout` 300초. 덮어쓰지 않으므로 §9.3의 "정산된 job은 정산된
  채로"가 유지된다.
- **테스트**: 실제 서브프로세스 4개를 한 파일에 경쟁시켜 정확히 400행, 전원 exit 0 확인.
  스레드로는 커넥션을 공유해 아무것도 증명하지 못한다.

### 3.2 D81 — 운영 실패를 모델의 답으로 기록

- **증상**: pod이 죽는 중에 디스패치된 페이지가 `INFRA_NETWORK`로 FAILED 확정.
- **원인**: 드라이버가 `arena/controller/retry.py`의 재시도 표를 아예 묻지 않았다.
- **수정**: `_retry_if_operational`이 실패 후 `retry.decide`를 참조해 허용량이 남아 있으면
  PENDING으로 되돌린다. 결정적 실패는 재시도 소진 후 정상 종결된다.

### 3.3 D82 — **오케스트레이터 과실**: 트리 kill로 pod 20개 고아

- **손실**: pod 20개 × 약 20분, 시간당 $0.49–$3.49. 드라이버가 죽어 원장 행이 없어
  청구 총액이 한동안 실제보다 작게 보였다.
- **원인**: 스케줄러를 `TaskStop`으로 멈췄고, 그것이 자식 드라이버까지 죽였다.
- **처리**: `cleanup-verify --execute`로 삭제, 두 API 목록으로 확인, 원장에 추정 정산.
- **규칙**: §2.3. 유료 자원을 소유한 프로세스와 그 부모는 트리로 죽이지 않는다.

이후 수퍼바이저가 4개 동시에 떠 있는 것도 발견해 PID로 정리하고 pod 10개를 더 삭제했다.
총 낭비 약 $32. 수퍼바이저에 단일 인스턴스 락(런처 쌍을 가족으로 인식)을 넣었다.

### 3.4 D83 — 슬라이스가 전부 같은 pod을 공유

- **원인**: RunPod은 pod 이름을 신원으로 취급한다. 이미 떠 있는 이름으로 create 하면
  그 pod을 그대로 돌려준다. replica index가 모두 0이라 `unlimited_ocr` 슬라이스 9개가
  한 pod을 공유했다. **병렬은 서류상으로만 존재했다.**
- **측정은 오염되지 않았다**: 마스터플랜 §14의 `max_concurrency_per_worker = 1`을 워커가
  `BoundedSemaphore`로 강제하므로 페이지는 어댑터 안에서 한 번에 하나씩 돌았다. 잃은
  것은 병렬성뿐이다.
- **수정**: 슬라이스 실행 시 `--replica-index`가 `--shard-index`를 기본값으로 따른다.

### 3.5 D84 — **네 모델이 몇 시간 굶은 진짜 원인**

- **증상**: `paddleocr_vl_1_6` 1.2%, `mineru_pipeline` 7.5%, `hpd_parsing` 11.6%에서
  pod을 못 받고 정지. 19개 슬라이스가 예산 전부를 점유.
- **원인**: D10이 Full Run pod에 6시간을 허용하고 예산 게이트가 **6시간치를 예약**했다.
  그런데 실제로 일한 pod 59개의 수명은 **중앙값 0.60시간, 최대 1.76시간**이었다.
  드라이버는 샤드가 끝나면 pod을 즉시 반납한다. 실제 청구의 10배를 예약한 $174.83이
  $300 soft cap을 막고 있었다.
- **수정 — cap은 손대지 않았다.** `--lifetime-hours`는 이미 진짜 watchdog이다(pod이
  `ARENA_MAX_POD_AGE_HOURS`를 들고 스스로 삭제). 문제는 예약이 그걸 무시한 것.
  `effective_pod_lifetime_hours`가 예약과 watchdog을 같은 숫자로 만들고, D10 상한으로
  양방향 클램프한다(8시간 요청 → 6시간 예약·강제). 소수는 올림한다. Full Run은 3시간을
  요청한다 — 측정된 모든 pod보다 길다.
- **3시간에 걸린 pod은?** 샤드가 안 끝난 채 삭제되고 §9.3이 RUNNING 페이지를 PENDING으로
  되돌린다. **부트스트랩 한 번을 잃을 뿐 페이지는 잃지 않는다.**
- **결과**: 적용 4분 만에 굶던 네 모델 전부가 pod을 받았다. `hpd_parsing`은 11.6% →
  33.9%, `mineru_vlm` 2.3% → 11.9%, `paddleocr_vl_1_6` 1.2% → 9.2%.
- 수퍼바이저의 자체 한도는 $285다(게이트 $300 바로 아래). 예전 $260은 여유가 너무 넓어
  **컨트롤러는 허용하는데 수퍼바이저만 막는** 상태를 만들었다.

### 3.6 D85 — **캐너리 provision-gate receipt 11개가 전부 덮어써짐**

- **증상**: `tests/core/test_contract_section_11.py`가 phase 불일치로 실패.
- **원인**: `canary_provision_receipt`가 모델당 경로 하나를 돌려주고 네 개 호출 지점이
  전부 거기에 썼다. Full Run이 캐너리 것을 덮고, 31개 슬라이스가 서로를 덮었다.
  원자적 쓰기라 손실이 조용했다.
- **잃은 것**: 각 캐너리 게이트가 기록한 licence·CUDA·pool 판정문.
- **남은 것**(이 경로에 있던 적이 없다): `receipts/canary-<model>.json`(캐너리 판정과
  페이지 결과), `receipts/canary-driver-<model>.json`, `cost/pod_provisioning.jsonl`
  (캐너리 pod별 phase·GPU·가격 스냅샷 digest·ceiling·승인 참조).
  **Full Run이 게이트하는 증거는 온전하다.**
- **수정**: 경로가 phase와 슬라이스를 담는다. 캐너리는 기존 파일명 유지.
- **재생성하지 않는다.** 캐너리를 다시 돌리면 새 pod·새 가격 스냅샷의 **새 측정에 옛
  날짜를 입히는** 것이 된다. 계약 테스트는 덮어써진 파일을 만나면 사고를 지목하며 skip
  한다 — 잘못된 phase를 받아들이도록 약화시키지 않았다.
- receipt: `receipts/incidents/provision-gate-receipts-20260904T0940Z-...json`

### 3.7 D87 — **미완료 런을 freeze 해버림 (오케스트레이터 과실)**

- **증상**: `freeze --model glm_ocr`을 `--execute` 없이 "미리보기" 삼아 실행 →
  4,179 / 5,132 페이지 상태로 manifest와 `FROZEN.json`이 실제로 봉인됨.
- **원인 둘**. `freeze`는 돈을 안 쓰므로 `--execute` 게이트 밖에 있었다. 그리고
  `freeze_model`이 큐에 "몇 개여야 하나"를 묻지 않고 receipt 디렉터리에 "몇 개 있나"만
  물었다. **`sample_count`는 receipt 개수라서 완결 여부를 말해주지 않는다.**
- **영향 없음**: scoring·report·ablation 어느 것도 읽기 전이었고, Full Run 드라이버는
  `FROZEN.json`을 보지 않으므로 glm_ocr은 계속 돌았다. 페이지 손실 0.
- **수정**: freeze가 큐에 물어 PENDING/ASSIGNED/RUNNING/PAUSED가 하나라도 있으면 개수를
  대며 거부한다. SUCCESS·FAILED·QUARANTINED는 답에 도달한 상태다(QUARANTINED는 큐의
  종결 상태이고, FAILED에 머문 job은 D81 재시도를 소진했다). 의도적 부분 freeze는
  `--allow-incomplete`가 필요하고 마커에 `complete: false` + planned/settled를 찍는다.
- 봉인됐던 파일은 삭제하지 않고
  `receipts/incidents/withdrawn-freeze-glm_ocr-20260904T0947Z/`로 격리했다.

### 3.8 D86 — 죽은 인프라 때문에 실패한 62페이지 재큐

`unlimited_ocr` 27 · `monkeyocrv2_b` 30 · `glm_ocr` 5. 전부 `INFRA_NETWORK`에 재시도
소진, 전부 D81 이전 드라이버가 디스패치한 것. 메시지는 사라진 pod의 HTTP 404(대부분 D82
고아)와 `monkeyocrv2_b` pod 6개의 HTTP 500. **그대로 얼렸다면 세 모델을 죽은 인프라로,
대부분은 내 실수로 채점하는 것이 된다.** retry_count를 지우고 PENDING으로 되돌렸다.
SUCCESS는 건드리지 않았다.

### 3.9 D88 — **secret 가드 오탐이 드라이버를 죽이고 있었다** (가장 최근)

- **증상**: `SecretLeak: value carries the 'sk-' credential prefix (field 'error')`가
  6개 슬라이스에서 **70회**. glm_ocr이 82.2%에서 한 시간 넘게 정지한 직접 원인.
- **원인**: `assert_secret_free`가 `prefix in text`로 **부분 문자열**을 봤다. 영어 단어
  세 개가 그 철자로 끝난다 — di**sk-**, ta**sk-**, ma**sk-**. 컨테이너 로그의
  "no disk-space left"를 인용한 `ReadinessError`가 OpenAI 키로 읽혔고, 드라이버는
  **일을 다 하고 나서 그 사실을 기록하려다 죽었다.** 슬라이스는 처음부터 다시 시작했다.
- **수정**: 접두사가 **토큰 시작 위치**에 있어야 한다 — 앞 글자가 영숫자가 아닐 것.
  문장 속 `sk-abc`, 값 시작, 공백·따옴표·`=`·`:`·`(` 뒤는 전부 여전히 걸린다. 실제 키는
  앞에 글자가 붙어 있지 않다. `disk-space`만 통과한다.
- **다른 규칙은 그대로다**: 실제 로드된 credential 동일성 검사, presigned URL 검사,
  opaque token 형태 검사 모두 무변경.
- **주의**: 이 수정 이전에 뜬 드라이버는 옛 모듈을 들고 있다. 수퍼바이저를 재기동해야
  새 드라이버가 고쳐진 코드를 쓴다(10:38Z에 재기동함).

### 3.10 mineru_vlm — 벤더 엔진 두 개가 서로 다른 답을 준다 (D78/D79)

가장 오래 잡은 문제. MinerU의 동기 `vllm-engine`은 같은 이미지에 **쓰레기 레이아웃**을
돌려주고, `vllm-async-engine`은 같은 프로세스·같은 kwargs로 정상 파싱한다. 벤더 CLI가
멀쩡해 보였던 이유는 3.4.4부터 CLI가 비동기 경로에서 `LocalAPIServer`를 띄우기 때문이다.
어댑터를 async 엔진으로 옮기고(전용 스레드에서 이벤트 루프 소유,
`asyncio.run_coroutine_threadsafe`) 캐너리 15/15 PASS.

`runtime.json`의 `expected_vlm_engine`을 `vllm-engine` → `vllm-async-engine`으로 바꿨다.
**runtime.json을 바꾸면 `inference_config_sha256`이 달라져 preflight가 캐너리를 거부한다.**
반드시:

```bash
python -m arena.registry resolve --offline
```

로 레지스트리를 다시 풀고, diff로 해당 모델 해시만 움직였는지 확인한다. 게이트는 pod을
빌리기 **전에** 거부하므로 돈은 안 나간다.

---

## 4. 남은 일 (순서 고정)

### 4.1 GPU 런 완주 — 약 12시간

수퍼바이저가 알아서 한다. 감시 포인트:

- `supervisor-state.json`의 `given_up`. 3스트라이크로 포기된 슬라이스가 쌓이면 원인을
  본다. **단, 자기 샤드가 이미 끝난 슬라이스는 즉시 종료하는 것이 정상이다**
  (`stop_reason=nothing_left`). 이건 고장이 아니다.
- 슬라이스 로그에 `SecretLeak`이 다시 보이면 D88 이전 드라이버가 남아 있다는 뜻 →
  수퍼바이저 재기동.
- 청구액이 $260을 넘으면 수퍼바이저가 새 pod을 못 띄운다. 예약이 정산되며 여유가
  생기지만, 진짜로 $300에 닿을 것 같으면 **창업자 판단 사항이다.** 스스로 cap을 올리지
  않는다.

### 4.2 freeze — 모델별로, 런이 끝난 뒤에만

```bash
python -m arena.controller freeze --model <model>
```

이제 미완료면 거부한다. **`--allow-incomplete`를 쓰지 마라.** 벤치마크 결과를 만드는
경로에서 부분 manifest는 의미가 없다.

### 4.3 scoring — 순서가 강제된다

```bash
python -m arena.scoring qa --model <m>        # 먼저 green
python -m arena.scoring prepare --model <m>
python -m arena.scoring score --model <m>
```

`--dry-run`이 실제 명령과 경로를 보여준다. 각 단계는 선행 단계가 없으면 우회하지 않고
거부한다. 벤치마크는 parsebench / omnidoc / olmocr 세 개.

### 4.4 TAVONEL Recovery/Adaptive ablation

```bash
python -m arena.tavonel signals
python -m arena.tavonel freeze-routes --variant <v>   # 1차 모델 채점 후에는 거부된다
python -m arena.tavonel replay --variant <v>
python -m arena.tavonel plan-recovery
python -m arena.tavonel disagreement [--correlate]
python -m arena.tavonel cost --variant <v>
```

이 레인은 돈을 안 쓴다. frozen output을 읽고 `tavonel/` 아래에 쓴다. 지키는 것은
**연산 순서**다.

### 4.5 리포트 · 정리 · 최종 보고

```bash
python -m arena.reports build
python -m arena.controller cleanup-verify --execute   # pod 0 확인
```

`evidence/full-run-forecast.{json,md}`는 이미 생성돼 있다(11개 모델 전부 캐너리 PASS,
예측 $173.50 / 마진 포함 $199.53 / 138 GPU-h). 실제가 이보다 높은 이유는 §3의 사고
손실 $41과 슬라이스마다 내는 부트스트랩 비용이다. **최종 보고서에 이 차이를 그대로
적는다.**

§35 최종 보고에는 비용·속도·오류·Pareto가 들어간다.

---

## 5. 다음 사람이 밟기 쉬운 함정 (요약)

1. **`TaskStop`으로 드라이버나 수퍼바이저를 죽이지 마라.** pod이 고아가 되고 계속 과금된다.
2. **`--execute`가 없다고 안전한 명령이 아니다.** `freeze`가 그래서 사고를 냈다.
   출력이 궁금해서 실행하기 전에 그 명령이 **쓰는지** 확인하라.
3. **RunPod `get-pod`/`list-pods` 금지.** env에 워커 토큰이 실린다.
4. **heredoc 안의 백슬래시가 반으로 준다.** 패치 스크립트는 Write 툴로.
5. **테스트 디렉터리를 합쳐 돌리지 마라.** scoring/tavonel conftest 충돌.
6. **runtime.json을 고치면 `arena.registry resolve --offline`을 반드시 다시 돌려라.**
7. **캐너리 저점수는 탈락이 아니다.** 캐너리는 런타임 자격 확인이지 품질 판정이 아니다.
8. **수퍼바이저가 여러 개 뜨지 않았는지 확인.** 같은 슬라이스에 드라이버가 둘이면 같은
   페이지를 두 pod에 줄 수 있다(§9.3이 두 번째 쓰기를 거부하지만 돈은 두 번 나간다).
9. **cap을 올리지 마라.** 예산 상향은 창업자 판단이다. §3.5가 보여주듯 대부분은
   예약이 부정확한 것이지 cap이 작은 게 아니다.
10. **commit/push 하지 마라.** 사용자가 명시적으로 요청할 때까지.

---

## 6. 파일 지도

| 경로 | 내용 |
|---|---|
| `ARENA_CONTRACT.md` §11.7 | 결정 D41–D88. 왜 그렇게 돼 있는지의 유일한 출처 |
| `evidence/phase2-launch-state.md` | 창업자용 상태 기록(승인·예산 산술·중지 방법) |
| `evidence/full-run-forecast.{json,md}` | 모델별 비용·시간 예측 |
| `receipts/canary-<model>.json` | 캐너리 판정과 15페이지 결과 |
| `receipts/full-run-driver-<model>-s<i>of<n>.json` | 슬라이스별 드라이버 기록 |
| `receipts/incidents/` | 사고 receipt 전부. 손실은 여기 남는다 |
| `receipts/authorizations/` | 지출 승인 receipt |
| `cost/pod_provisioning.jsonl` | pod별 예약(ceiling) |
| `cost/pod_ledger.jsonl` | pod별 실제 청구 |
| `frozen_outputs/<model>/` | manifest.jsonl + FROZEN.json |
| `runs/<model>/` | run-summary.json, checkpoint, `STOP` 파일 위치 |
| `scratchpad/supervise_full.py` | 수퍼바이저 (네임스페이스 밖, 스크래치패드) |
| `scratchpad/fullrun/*.log` | 슬라이스 로그 |

---

## 7. 한 줄 요약

GPU 레인 35.8%, Opus 레인 62.9%, 청구 $126.50, 예상 총액 $235. 전 테스트 2,202건 통과.
**막고 있던 것은 cap이 아니라 부정확한 예약이었고, 마지막으로 드라이버를 죽이던 것은
`disk-`를 API 키로 읽던 secret 가드였다.** 둘 다 고쳤다. 남은 것은 시간이다.

상태: **FULL_RUN_EXECUTED (진행 중)** — freeze·scoring·report는 아직 시작하지 않았다.
