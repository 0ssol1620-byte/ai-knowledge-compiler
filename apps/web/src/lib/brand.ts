export const PUBLIC_BRAND = {
  name: "FOLYNTA",
  category: "The Knowledge Compiler",
  tagline: "From every page, a system of knowledge.",
  legalStatus: "clearance-pending",
  korean: {
    hero: "흩어진 문서를\n하나의 지식 시스템으로.",
    category:
      "모든 페이지를 구조화·검증·연결하여 사람이 AI가 재사용할 수 있는 지식으로 컴파일합니다.",
    proof: "모든 중요한 결과를 원문으로 되돌아가 확인할 수 있습니다.",
    enterprise:
      "정책과 근거가 보존되는 Verified Knowledge Infrastructure.",
  },
  english: {
    hero: "From scattered documents\nto one knowledge system.",
    category:
      "Compile every page into structured, verified, connected knowledge that people and AI can reuse.",
    proof: "Return every important result to the exact source that supports it.",
    enterprise:
      "Verified Knowledge Infrastructure that preserves policy and proof.",
  },
} as const;

export type PublicBrand = typeof PUBLIC_BRAND;
