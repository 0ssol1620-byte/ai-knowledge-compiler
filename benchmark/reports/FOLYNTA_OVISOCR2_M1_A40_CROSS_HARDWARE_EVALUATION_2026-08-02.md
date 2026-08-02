# FOLYNTA OvisOCR2 M1 A40 런타임 및 교차 환경 평가

완료일: 2026-08-02 KST  
판정 범위: 내부 M1 런타임 smoke 및 교차 환경 진단  
프로덕션 승격: 불가

## 최종 판정

OvisOCR2 0.9B는 RunPod Secure Cloud의 NVIDIA A40에서 공식
`vllm/vllm-openai` 이미지와 vLLM 0.22.1+cu129 조합으로 실제 실행됐다.
6개 문서 family를 정확히 3회 처리했고 18/18 성공, 하드 실패 0, A40 내부
byte-exact 재현성 6/6을 기록했다. 모델 payload 15개 파일과 1,731,023,589
바이트는 기존 RTX 4090 평가 때 사용한 payload와 모두 일치했다.

이 결과는 A40 런타임 호환성을 입증하지만 순수 하드웨어 A/B 완료를 뜻하지
않는다. A40과 기존 4090 실행의 GPU·드라이버·Python·Pillow가 달랐기
때문이다. 동일 6페이지에서 aggregate metric 6개 중 text edit distance만
0.000614 차이였지만, 원문 Markdown hash는 3/6만 같았다. 따라서 출력
동등성을 가정하는 캐시나 서명 정책은 GPU/환경 identity를 반드시 포함해야 한다.

## 동결 계약

| 항목 | 값 |
| --- | --- |
| 모델 | OvisOCR2 0.9B |
| 모델 revision | `65c619d374b55d4152e85150fc1b003700bc1f0c` |
| 모델 payload | 15 files / 1,731,023,589 bytes |
| cache 제외 manifest | `50b8a6cff82992375d321d9f9b918bdd43c9a48fe1615e40bfaa10fcfc33cc3d` |
| 컨테이너 | `vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05` |
| A40 runtime | Python 3.12.13 / torch 2.11.0+cu129 / vLLM 0.22.1+cu129 / Pillow 12.2.0 |
| GPU | NVIDIA A40 46,068 MiB / driver 570.195.03 |
| 입력 | OmniDocBench demo에서 고정한 6개 family |
| 반복 | 동일 process, 정확히 3회 |
| GT 격리 | inference worker에 GT 없음 |
| evaluator | `OmniDocBench@193627ae9e97d89188468ed1ee3b7a856ff76044` |
| GT subset hash | `1b14ce5d3cb4ad9570a3cbc0034601d1570439da0f3dbcd89d66761263374dd4` |

## A40 공식 partial metric

Edit distance는 낮을수록, TEDS는 높을수록 좋다.

| Metric | A40 |
| --- | ---: |
| Text edit distance | 0.211692 |
| Formula edit distance | 0.109726 |
| Table TEDS | 0.803456 |
| Table structure TEDS | 0.863782 |
| Table edit distance | 0.118638 |
| Reading-order edit distance | 0.266442 |

세 evaluator 반복의 metric result hash는 모두 같았다. CDM과 overall은 이
portable lane에서 사용할 수 없으며 0으로 대체하지 않았다.

## A40 성능·비용

| 항목 | 값 |
| --- | ---: |
| 모델 초기화 | 152.640초 |
| repeat 1 | 97.069초 |
| repeat 2 | 77.001초 |
| repeat 3 | 77.087초 |
| 평균 | 13.953초/페이지 |
| 관측 GPU 단가 | $0.44/시간 |
| 추정 inference runtime 비용 | $0.001705/페이지 |

비용은 inference 구간만 단가에 곱한 값이다. Pod 준비, 이미지 pull, 모델
다운로드, 로컬 evaluator, 저장·전송, 세금과 실제 invoice는 포함하지 않는다.

## 같은 6페이지의 기존 RTX 4090 출력과 비교

| Metric | A40 | 기존 4090 | A40 - 4090 |
| --- | ---: | ---: | ---: |
| Text edit distance | 0.211692 | 0.212305 | -0.000614 |
| Formula edit distance | 0.109726 | 0.109726 | 0 |
| Table TEDS | 0.803456 | 0.803456 | 0 |
| Table structure TEDS | 0.863782 | 0.863782 | 0 |
| Table edit distance | 0.118638 | 0.118638 | 0 |
| Reading-order edit distance | 0.266442 | 0.266442 | 0 |

A40는 6/6 페이지가 3회 byte-exact였고 기존 4090 subset은 5/6이었다.
그러나 A40 repeat 1과 4090 repeat 1의 Markdown이 완전히 같은 페이지는
3/6뿐이었다. aggregate 점수 유사성과 원문 artifact 동일성은 별개의 계약이다.

## 제품 반영 결정

1. A40는 OvisOCR2의 48GB fallback 런타임 후보로 유지한다.
2. OvisOCR2는 기존 18×3 포트폴리오 결과대로 default가 아니라 shadow lane을 유지한다.
3. 캐시 key·proof receipt·prediction signature에 GPU, driver, image digest,
   Python 및 핵심 dependency identity를 포함한다.
4. 순수 하드웨어 A/B는 동일 immutable image와 동일 dependency로 4090과
   A40를 다시 실행하기 전까지 `NOT_RUN`이다.
5. 6페이지 M1 결과를 M2 200페이지, M3 public core 또는 production SLO로
   확장 해석하지 않는다.

## 증거

- 기계 판독 evidence:
  `benchmark/reports/folynta-ovisocr2-m1-a40-cross-hardware-evidence-2026-08-02.json`
- A40 run summary SHA-256:
  `e41b04e29f9084f5d5f3a4896c5f0dc5520a05f1fcbd7f21abf4195bbadef26e`
- A40 evidence archive SHA-256:
  `859a73bc3bbcd1261763201db4ca5a96522ba2a6781a8892aeef73ca6c9c2406`
- 최종 RunPod 인벤토리: 0 Pods

초기 18페이지 GT를 그대로 넣어 page count가 18로 반환된 채점은
`official-invalid-full-gt-evaluation`에 폐기 증거로 보존했다. 이후 evaluator가
prediction file 수와 official result page count의 정확한 일치를 강제하도록
수정했으며, 6페이지 evaluator-only GT로 재실행한 결과만 위 표에 사용했다.
