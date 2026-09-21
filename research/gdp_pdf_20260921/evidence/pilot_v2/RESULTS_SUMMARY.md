# GDP.pdf two-arm experiment - RESULTS SUMMARY / 결과 요약

**NOT OFFICIAL-COMPARABLE / 공식 비교 불가.** Surface uses the Read tool, the judge is Opus and not `gemini-3.5-flash`, and the dataset is pinned to the head revision because the sealed revision's parquet blob is stranded on a retired CDN. Full detail in `report.md`.

## EN

- Cells scored: **20**.
- `native_pdf`: macro 70.0% (7/10), micro 94.4% (94/100 criteria).
- `compiled_context_pdf`: macro 40.0% (4/10), micro 70.5% (74/100 criteria).
- Paired delta (compiled - native): **macro -30.0 pp, micro -23.9 pp (paired n = 10)**.
- Result, plainly: **the compiled arm did NOT beat the native arm** on this corpus, this surface and this judge.
- Secondary cut, tasks where a compiled packet existed at all (a different denominator, not a replacement headline): macro -12.5 pp, micro -4.9 pp (n = 8).
- Adapter failures kept in the denominator: 2 documents with no text layer, scored zero, never dropped.
- Compiled packet size: median 390,731 characters, 4 of 8 truncated by the stated budget rule. Token counts are NOT_MEASURED.

## KO / 한국어

- 채점된 셀: **20**개.
- `native_pdf`: macro 70.0% (7/10), micro 94.4% (94/100 criteria).
- `compiled_context_pdf`: macro 40.0% (4/10), micro 70.5% (74/100 criteria).
- 쌍으로 비교한 차이(컴파일 - 네이티브): **macro -30.0 pp, micro -23.9 pp (paired n = 10)**.
- 결론을 그대로 적으면: 이 코퍼스, 이 서페이스, 이 판정자 기준으로 **컴파일 컨텍스트 암은 네이티브 암을 이기지 못했다**.
- 보조 단면(컴파일 패킷이 실제로 존재한 과제만; 분모가 다르며 헤드라인 대체가 아니다): macro -12.5 pp, micro -4.9 pp (n = 8).
- 분모에 그대로 남긴 어댑터 실패: 텍스트 레이어가 없는 2개 문서. 0점 처리하되 제외하지 않았다.
- 컴파일 패킷 크기: 중앙값 390,731 자, 8개 중 4개가 명시된 예산 규칙으로 잘렸다. 토큰 수는 측정하지 않았다(NOT_MEASURED).
