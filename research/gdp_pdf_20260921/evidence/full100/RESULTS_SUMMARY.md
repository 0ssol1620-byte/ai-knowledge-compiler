# GDP.pdf two-arm experiment - RESULTS SUMMARY / 결과 요약

**NOT OFFICIAL-COMPARABLE / 공식 비교 불가.** Surface uses the Read tool, the judge is Opus and not `gemini-3.5-flash`, and the dataset is pinned to the head revision because the sealed revision's parquet blob is stranded on a retired CDN. Full detail in `report.md`.

## EN

- Cells scored: **200**.
- `native_pdf`: macro 31.0% (31/100), micro 79.3% (1032/1275 criteria).
- `compiled_context_pdf`: macro 27.0% (27/100), micro 71.3% (948/1275 criteria).
- Paired delta (compiled - native): **macro -4.0 pp, micro -8.0 pp (paired n = 100)**.
- Result, plainly: **the compiled arm did NOT beat the native arm** on this corpus, this surface and this judge.
- Secondary cut, tasks where a compiled packet existed at all (a different denominator, not a replacement headline): macro -1.1 pp, micro +0.9 pp (n = 89).
- Adapter failures kept in the denominator: 11 documents with no text layer, scored zero, never dropped.
- Compiled packet size: median 399,387 characters, 53 of 89 truncated by the stated budget rule. Token counts are NOT_MEASURED.

## KO / 한국어

- 채점된 셀: **200**개.
- `native_pdf`: macro 31.0% (31/100), micro 79.3% (1032/1275 criteria).
- `compiled_context_pdf`: macro 27.0% (27/100), micro 71.3% (948/1275 criteria).
- 쌍으로 비교한 차이(컴파일 - 네이티브): **macro -4.0 pp, micro -8.0 pp (paired n = 100)**.
- 결론을 그대로 적으면: 이 코퍼스, 이 서페이스, 이 판정자 기준으로 **컴파일 컨텍스트 암은 네이티브 암을 이기지 못했다**.
- 보조 단면(컴파일 패킷이 실제로 존재한 과제만; 분모가 다르며 헤드라인 대체가 아니다): macro -1.1 pp, micro +0.9 pp (n = 89).
- 분모에 그대로 남긴 어댑터 실패: 텍스트 레이어가 없는 11개 문서. 0점 처리하되 제외하지 않았다.
- 컴파일 패킷 크기: 중앙값 399,387 자, 89개 중 53개가 명시된 예산 규칙으로 잘렸다. 토큰 수는 측정하지 않았다(NOT_MEASURED).
