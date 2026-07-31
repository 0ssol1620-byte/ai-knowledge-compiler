import { expect, test } from "@playwright/test";

const baseURL = "http://127.0.0.1:3000";

test.beforeEach(async ({ context }) => {
  await context.addCookies([
    {
      name: "structara_locale",
      value: "ko",
      url: baseURL,
      sameSite: "Lax",
    },
  ]);
});

test("Korean locale remains consistent across marketing and core product workflows", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  await expect(
    page.getByRole("heading", { name: /AI의 성능은 전달받는 지식의 품질/ }),
  ).toBeVisible();
  const desktopProductLink = page
    .getByRole("navigation", { name: "주요 내비게이션" })
    .getByRole("link", { name: "제품" });
  if (await desktopProductLink.isVisible()) {
    await expect(desktopProductLink).toBeVisible();
  } else {
    await page.getByRole("button", { name: "내비게이션 열기" }).click();
    const mobileNavigation = page.getByRole("navigation", {
      name: "모바일 내비게이션",
    });
    await expect(
      mobileNavigation.getByText("제품", { exact: true }),
    ).toBeVisible();
    await expect(
      mobileNavigation.getByRole("link", { name: "개요" }),
    ).toBeVisible();
  }

  await page.goto("/product/verify");
  await expect(
    page.getByRole("heading", { name: "추출 결과를 믿지 말고 검증하세요." }),
  ).toBeVisible();

  await page.goto("/projects");
  await expect(
    page.getByRole("heading", { name: "프로젝트", exact: true }),
  ).toBeVisible();
  const projectSearch = page.getByRole("textbox", { name: "프로젝트 검색" });
  await projectSearch.fill("evidence fidelity");
  await expect(page.getByRole("table")).toContainText(
    "RAG evidence fidelity study",
  );
  await page
    .getByRole("button", { name: "선택 RAG evidence fidelity study" })
    .click();
  await expect(page.getByText("1 개 선택됨")).toBeVisible();

  await page.goto("/review");
  await expect(
    page.getByRole("heading", { name: "검토 Studio" }),
  ).toBeVisible();
  await expect(page.getByText("인터랙티브 샘플")).toBeVisible();
  await page.getByRole("button", { name: "교체값 승인" }).click();
  await expect(page.getByText("최근 감사 이벤트")).toBeVisible();

  await page.goto("/knowledge-bases");
  await expect(
    page.getByRole("heading", { name: "지식 Studio" }),
  ).toBeVisible();
  const knowledgeSearch = page.getByRole("textbox", { name: "지식 검색" });
  await knowledgeSearch.fill("revenue");
  await expect(page.getByText(/1 개 일치 노트/)).toBeVisible();
  await page
    .locator(".knowledge-explorer")
    .getByRole("button", { name: "근거" })
    .click();
  await expect(page.getByText(/근거 관점/)).toBeVisible();
});

test("language switch persists and returns the product to English", async ({
  page,
}) => {
  await page.goto("/");
  const switcher = page.getByRole("group", { name: "언어 선택" }).first();
  await switcher.getByRole("button", { name: "EN" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(
    page.getByRole("heading", { name: /Your AI is only as good/ }),
  ).toBeVisible();

  await page.goto("/projects");
  await expect(
    page.getByRole("heading", { name: "Projects", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Search projects" }),
  ).toBeVisible();
});

test("Korean authentication, onboarding, and quick-convert controls stay actionable", async ({
  page,
}) => {
  await page.goto("/signup");
  await expect(
    page.getByRole("heading", { name: "계정 만들기" }),
  ).toBeVisible();
  await expect(page.getByLabel("표시 이름")).toBeVisible();
  await expect(page.getByLabel("이메일")).toBeVisible();
  await expect(page.getByLabel("비밀번호")).toBeVisible();

  await page.goto("/onboarding");
  await expect(
    page.getByRole("heading", { name: "무엇을 만들고 싶나요?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "AI / RAG 지식" }).click();
  await page.getByRole("button", { name: "계속" }).click();
  await page.getByRole("button", { name: "연구 논문" }).click();
  await page.getByRole("button", { name: "계속" }).click();
  await page.getByRole("button", { name: "외부 처리 사용 안 함" }).click();
  await page.getByRole("button", { name: "계속" }).click();
  await page.getByRole("button", { name: "파일 선택" }).click();
  await expect(page.getByRole("link", { name: /업로드 열기/ })).toBeVisible();

  await page.goto("/quick-convert");
  await expect(
    page.getByRole("heading", { name: "새 변환 시작" }),
  ).toBeVisible();
  await page.getByLabel("업로드할 파일 선택").setInputFiles({
    name: "sample.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Source-linked sample"),
  });
  await expect(page.getByText("sample.md")).toBeVisible();
  await page.getByRole("button", { name: /1개 문서 사전 분석 실행/ }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "데모 모드에서는 원본을 업로드" }),
  ).toBeVisible();
});
