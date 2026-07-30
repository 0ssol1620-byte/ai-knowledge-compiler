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
    page.getByRole("heading", { name: "확인 메일을 요청했습니다" }),
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
    page.getByRole("heading", { name: "이메일 확인 완료" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "워크스페이스 열기" }).click();
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
  await page.getByRole("button", { name: "1개 문서 사전 분석" }).click();
  const analyzeResponse = await analyzeResponsePromise;
  expect(analyzeResponse.ok()).toBe(true);
  const documentId = new URL(analyzeResponse.url()).pathname.split("/")[3]!;

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
  const compileBody = (await compileResponse.json()) as { job_id: string };
  const compileRequest = compileResponse.request();
  const duplicateCompile = await page.request.post(compileResponse.url(), {
    headers: {
      "Idempotency-Key": compileRequest.headers()["idempotency-key"]!,
      "Content-Type": "application/json",
    },
    data: compileRequest.postDataJSON(),
  });
  expect(duplicateCompile.status()).toBe(202);
  expect(await duplicateCompile.json()).toEqual(compileBody);

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

  const replayResponse = await page.request.get(
    `http://127.0.0.1:8100/v1/jobs/${compileBody.job_id}/events/replay`,
  );
  expect(replayResponse.ok()).toBe(true);
  const replayEvents = (await replayResponse.json()) as Array<{
    event_id: string;
    sequence: number;
  }>;
  expect(replayEvents.length).toBeGreaterThan(0);
  expect(new Set(replayEvents.map((event) => event.event_id)).size).toBe(
    replayEvents.length,
  );
  expect(replayEvents.map((event) => event.sequence)).toEqual(
    [...replayEvents].map((event) => event.sequence).sort((a, b) => a - b),
  );

  await page.reload();
  await expect(page.getByText("처리 완료", { exact: true })).toBeVisible();
  await expect(
    page
      .getByLabel("Markdown 결과")
      .getByRole("button", { name: /p\.1/ })
      .first(),
  ).toBeVisible();

  const seedReview = await page.request.post(
    "http://127.0.0.1:8100/__test__/seed-review",
    {
      headers: { "X-AKC-Test-Support-Key": testSupportKey },
      data: { document_id: documentId },
    },
  );
  expect(seedReview.ok()).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: /Review\s+1/ }).click();
  const reviewDialog = page.getByRole("dialog", { name: "Review queue" });
  await expect(reviewDialog).toBeVisible();
  await reviewDialog
    .getByRole("textbox", { name: "Direct replacement" })
    .fill("1,234 — verified against the immutable source.");
  const resolveResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/v1\/review-items\/[^/]+\/resolve$/.test(
        new URL(response.url()).pathname,
      ),
  );
  await reviewDialog.getByRole("button", { name: "Apply edit" }).click();
  expect((await resolveResponsePromise).ok()).toBe(true);
  await expect(
    reviewDialog.getByRole("button", { name: "Resolved" }),
  ).toBeVisible();
  await reviewDialog
    .getByRole("button", { name: "Close review queue" })
    .click();
  await expect(reviewDialog).toBeHidden();

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

  const deletionResponse = await page.request.delete(
    `http://127.0.0.1:8100/v1/documents/${documentId}`,
    {
      headers: { "Idempotency-Key": `e2e-delete-${unique}` },
    },
  );
  expect(deletionResponse.status()).toBe(202);
  const deletion = (await deletionResponse.json()) as {
    id: string;
    status_url: string;
  };
  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          `http://127.0.0.1:8100${deletion.status_url}`,
        );
        return response.ok() ? (await response.json()).state : "unavailable";
      },
      { timeout: 30_000 },
    )
    .toBe("purged");
  expect(
    (
      await page.request.get(
        `http://127.0.0.1:8100/v1/documents/${documentId}/analysis`,
      )
    ).status(),
  ).toBe(404);
});
