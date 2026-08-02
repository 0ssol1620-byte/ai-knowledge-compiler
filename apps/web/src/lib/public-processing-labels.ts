import type { StructaraLocale } from "@/lib/locale";

function normalized(value: string | null | undefined): string {
  return (value ?? "").trim().toLocaleLowerCase();
}

export function publicCandidateLabel(
  value: string | null | undefined,
  locale: StructaraLocale = "en",
): string {
  const candidate = normalized(value);
  if (candidate.includes("native") || candidate.includes("source")) {
    return locale === "ko" ? "원문 구조 후보" : "Source-native candidate";
  }
  if (
    candidate.includes("ocr") ||
    candidate.includes("paddle") ||
    candidate.includes("mineru") ||
    candidate.includes("vision") ||
    candidate.includes("visual")
  ) {
    return locale === "ko" ? "시각 비교 후보" : "Visual comparison candidate";
  }
  return locale === "ko" ? "비교 후보" : "Comparison candidate";
}

export function publicRouteLabel(
  value: string | null | undefined,
  locale: StructaraLocale = "en",
): string {
  const route = normalized(value);
  if (route.includes("private")) {
    return locale === "ko" ? "비공개 처리 경로" : "Private processing route";
  }
  if (route.includes("native") || route.includes("source")) {
    return locale === "ko" ? "원문 구조 경로" : "Source-native route";
  }
  if (route.includes("precision")) {
    return locale === "ko" ? "정밀 문서 경로" : "Precision document route";
  }
  if (
    route.includes("ocr") ||
    route.includes("paddle") ||
    route.includes("mineru") ||
    route.includes("vision") ||
    route.includes("visual")
  ) {
    return locale === "ko" ? "시각 문서 경로" : "Visual document route";
  }
  if (route.includes("balanced")) {
    return locale === "ko" ? "균형 문서 경로" : "Balanced document route";
  }
  return locale === "ko" ? "문서 처리 경로" : "Document processing route";
}

export function publicOriginLabel(
  value: string | null | undefined,
  locale: StructaraLocale = "en",
): string {
  const origin = normalized(value);
  if (origin.includes("native")) {
    return locale === "ko" ? "원문 추출" : "Source extracted";
  }
  if (origin.includes("ocr") || origin.includes("visual")) {
    return locale === "ko" ? "시각 추출" : "Visual extraction";
  }
  if (origin.includes("rule") || origin.includes("structure")) {
    return locale === "ko" ? "구조 복구" : "Structure rebuilt";
  }
  if (origin.includes("summar")) {
    return locale === "ko" ? "생성 요약" : "Generated summary";
  }
  if (origin.includes("infer")) {
    return locale === "ko" ? "생성 추론" : "Generated inference";
  }
  if (origin.includes("ai") || origin.includes("reconstruct")) {
    return locale === "ko" ? "생성 복구" : "Generated reconstruction";
  }
  if (origin.includes("user")) {
    return locale === "ko" ? "사용자 편집" : "User edited";
  }
  return locale === "ko" ? "기록된 변환" : "Recorded transformation";
}
