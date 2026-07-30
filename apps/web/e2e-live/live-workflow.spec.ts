import { expect, test } from "@playwright/test";

const testSupportKey = "live-e2e-verification-support-key-2026";

test("real API journey preserves provenance through export", async ({
  page,
}) => {
  const unique = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  const email = `live-e2e-${unique}@example.test`;
  const filename = "e2e-source.txt";

  await page.goto("/login?mode=register");
  await page.getByLabel("워크스페이스 이름").fill(`E2E Workspace ${unique}`);
  await page.getByLabel("표시 이름").fill("Live E2E Owner");
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill("Correct-Horse-Battery-Staple-2026!");

  const registerResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/v1/auth/register",
  );
  await page.getByRole("button", { name: "워크스페이스 만들기" }).click();
  const registerResponse = await registerResponsePromise;
  expect(registerResponse.ok()).toBe(true);
  expect((await registerResponse.json()).email_verified).toBe(false);

  await expect(
    page.getByRole("heading", { name: "Verification email requested" }),
  ).toBeVisible();
  const captureResponse = await page.request.post(
    "http://127.0.0.1:8100/__test__/verification-token",
    {
      headers: { "X-AKC-Test-Support-Key": testSupportKey },
      data: { email },
    },
  );
  expect(captureResponse.ok()).toBe(true);
  const capture = (await captureResponse.json()) as { token: string };
  await page.goto(
    `/verify-email?verification=1#token=${encodeURIComponent(capture.token)}`,
  );
  await expect(
    page.getByRole("heading", { name: "You are ready" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Open workspace" }).click();
  await page.waitForURL("http://127.0.0.1:3100/home");
  await expect(
    page.getByRole("heading", { name: "원문에서 검증 가능한 지식까지" }),
  ).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(
      [
        "Evidence-grounded systems keep every claim linked to its source.",
        "This native text fixture exercises upload, analysis, compilation, and export.",
      ].join("\n"),
      "utf8",
    ),
  });
  const analyzeResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/v1\/documents\/[^/]+\/analyze$/.test(new URL(response.url()).pathname),
  );
  await page.getByRole("button", { name: "1개 파일 분석하기" }).click();
  const analyzeResponse = await analyzeResponsePromise;
  expect(analyzeResponse.ok()).toBe(true);

  await page.waitForURL(/\/workspace\?document=[0-9a-f-]+&estimate=1$/);
  await expect(
    page.getByRole("heading", { name: "처리 전 견적을 확인하세요" }),
  ).toBeVisible();
  await expect(page.getByText("Native text")).toBeVisible();
  await expect(page.getByText("사용 안 함")).toBeVisible();

  await page.getByRole("checkbox").check();
  const compileResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/v1\/documents\/[^/]+\/compile$/.test(new URL(response.url()).pathname),
  );
  const snapshotResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      /\/v1\/jobs\/[^/]+$/.test(new URL(response.url()).pathname),
  );
  const eventStreamResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      /\/v1\/jobs\/[^/]+\/events$/.test(new URL(response.url()).pathname),
  );
  await page.getByRole("button", { name: "처리 시작" }).click();

  const [compileResponse, snapshotResponse, eventStreamResponse] =
    await Promise.all([
      compileResponsePromise,
      snapshotResponsePromise,
      eventStreamResponsePromise,
    ]);
  expect(compileResponse.ok()).toBe(true);
  expect(snapshotResponse.ok()).toBe(true);
  expect(eventStreamResponse.ok()).toBe(true);
  expect(eventStreamResponse.headers()["content-type"]).toContain(
    "text/event-stream",
  );

  await page.waitForURL(/\/workspace\?job=[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: filename })).toBeVisible();
  await expect(page.getByLabel("Document version 1")).toBeVisible();
  await expect(page.getByText("처리 완료", { exact: true })).toBeVisible({
    timeout: 60_000,
  });

  const sourcePanel = page.getByLabel("원본 문서");
  const markdownPanel = page.getByLabel("Markdown 결과");
  await expect(sourcePanel).toBeVisible();
  await expect(markdownPanel).toBeVisible();
  await expect(
    markdownPanel.getByRole("button", { name: /p\.1/ }).first(),
  ).toBeVisible();

  const provenanceLink = markdownPanel
    .getByRole("button", { name: /블록과 원본 연결/ })
    .first();
  await provenanceLink.click();
  await expect(sourcePanel.locator(".bbox-rect.active")).toBeVisible();

  const exportButton = page.getByRole("button", { name: "Export" });
  await expect(exportButton).toBeEnabled();
  await exportButton.click();
  const exportDialog = page.getByRole("dialog", {
    name: "지식 패키지 만들기",
  });
  await expect(exportDialog).toBeVisible();

  const exportResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/v1\/jobs\/[^/]+\/exports$/.test(new URL(response.url()).pathname),
  );
  const downloadPromise = page.waitForEvent("download");
  await exportDialog.getByRole("button", { name: "Export package" }).click();
  const [exportResponse, download] = await Promise.all([
    exportResponsePromise,
    downloadPromise,
  ]);
  expect(exportResponse.ok()).toBe(true);
  expect(download.suggestedFilename()).toMatch(/^akc-export-[0-9a-f-]+\.zip$/);
  expect(await download.failure()).toBeNull();
});
