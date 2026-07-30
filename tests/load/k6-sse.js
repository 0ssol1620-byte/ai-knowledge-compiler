import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

import { guardedBaseUrl, requireFixture } from "./safety.js";

const baseUrl = guardedBaseUrl();
requireFixture(["AKC_TEST_JOB_ID"]);
const connectionSuccess = new Rate("akc_sse_connection_success");
const reconnectDuration = new Trend("akc_sse_reconnect_duration", true);

export const options = {
  scenarios: {
    sse_1000: {
      executor: "constant-vus",
      vus: 1000,
      duration: "5m",
      gracefulStop: "15s",
    },
  },
  thresholds: {
    akc_sse_connection_success: ["rate>=0.995"],
    akc_sse_reconnect_duration: ["p(95)<5000"],
  },
  discardResponseBodies: true,
};

export default function () {
  const started = Date.now();
  const response = http.get(
    `${baseUrl}/v1/jobs/${encodeURIComponent(__ENV.AKC_TEST_JOB_ID)}/events`,
    {
      headers: {
        Accept: "text/event-stream",
        ...(__ENV.AKC_TEST_TOKEN
          ? { Authorization: `Bearer ${__ENV.AKC_TEST_TOKEN}` }
          : {}),
        "Last-Event-ID": __ENV.AKC_LAST_EVENT_ID || "0",
      },
      timeout: "15s",
      tags: { endpoint: "job_events" },
    },
  );
  const connected = check(response, {
    "SSE handshake is successful": (value) => value.status === 200,
    "SSE content type is explicit": (value) =>
      String(value.headers["Content-Type"] || "").includes("text/event-stream"),
  });
  connectionSuccess.add(connected);
  reconnectDuration.add(Date.now() - started);
}
