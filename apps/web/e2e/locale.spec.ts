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
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  await expect(
    page.getByRole("heading", {
      name: "흩어진 문서를 하나의 지식 시스템으로.",
    }),
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

  await page.goto("/review?project=project-7&token=secret");
  await expect(page).toHaveURL(/\/integrity\?project=project-7$/);
  await expect(
    page.getByRole("heading", {
      name: "자동 복구를 먼저 수행하고, 근거가 멈춘 곳만 사람이 판단합니다",
    }),
  ).toBeVisible();
  await expect(page.getByText("선택한 컬렉션이 없습니다")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("secret");
  await expect(page.locator("body")).not.toContainText("검토 Studio");

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
  isMobile,
}) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  if (isMobile) {
    await page.getByRole("button", { name: "내비게이션 열기" }).click();
  }
  const switcher = page.getByRole("group", { name: "언어 선택" }).first();
  await switcher.getByRole("button", { name: "EN" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(
    page.getByRole("heading", {
      name: "From scattered documents to one knowledge system.",
    }),
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
  await expect(
    page.getByRole("link", { name: "컬렉션 수집 열기" }),
  ).toBeVisible();

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
