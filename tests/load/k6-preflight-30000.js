import http from "k6/http";
import { check, fail } from "k6";
import { Trend } from "k6/metrics";

import { guardedBaseUrl, jsonHeaders, requireFixture } from "./safety.js";

const baseUrl = guardedBaseUrl();
requireFixture([
  "AKC_TEST_TOKEN",
  "AKC_TEST_COLLECTION_ID",
  "AKC_RUN_ID",
  "AKC_PREFLIGHT_FIXTURE_ATTESTATION",
]);
const fixture = JSON.parse(
  open(__ENV.AKC_PREFLIGHT_FIXTURE_ATTESTATION, "t"),
);
const preflightDuration = new Trend("akc_preflight_precise_duration", true);
const knownPagesObserved = new Trend("akc_preflight_known_pages");

if (
  fixture.schema_version !== "1.0.0" ||
  fixture.synthetic !== true ||
  fixture.customer_data !== false ||
  fixture.collection_id !== __ENV.AKC_TEST_COLLECTION_ID ||
  fixture.known_pages !== 30000 ||
  !/^sha256:[0-9a-f]{64}$/.test(fixture.manifest_sha256 || "") ||
  !/^sha256:[0-9a-f]{64}$/.test(fixture.fixture_sha256 || "")
) {
  throw new Error(
    "AKC_PREFLIGHT_FIXTURE_ATTESTATION must bind an exact synthetic 30,000-page collection",
  );
}

export const options = {
  scenarios: {
    preflight_30000_pages: {
      executor: "shared-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "16m",
    },
  },
  thresholds: {
    checks: ["rate==1"],
    akc_preflight_known_pages: ["min==30000", "max==30000"],
    akc_preflight_precise_duration: ["p(95)<900000"],
  },
};

export default function () {
  const started = Date.now();
  const response = http.post(
    `${baseUrl}/v1/collections/${encodeURIComponent(__ENV.AKC_TEST_COLLECTION_ID)}/preflight`,
    null,
    {
      headers: jsonHeaders(__ENV.AKC_TEST_TOKEN, {
        "Idempotency-Key": `scale-30k-preflight-${__ENV.AKC_RUN_ID}`,
      }),
      timeout: "16m",
      tags: { endpoint: "collection_preflight_30000" },
    },
  );
  preflightDuration.add(Date.now() - started);
  const accepted = check(response, {
    "preflight status is 201": (value) => value.status === 201,
    "preflight response is JSON": (value) =>
      String(value.headers["Content-Type"] || "").includes("application/json"),
  });
  if (!accepted) fail(`30,000-page preflight failed with HTTP ${response.status}`);
  const result = response.json();
  knownPagesObserved.add(Number(result.known_pages));
  if (
    !check(result, {
      "exactly 30,000 known pages are observed": (value) =>
        value.known_pages === 30000,
      "fixture collection is unchanged": (value) =>
        value.collection_id === __ENV.AKC_TEST_COLLECTION_ID,
      "preflight output is content-addressed": (value) =>
        /^[0-9a-f]{64}$/.test(value.output_sha256 || ""),
    })
  ) {
    fail("preflight response did not bind the attested 30,000-page fixture");
  }
}
