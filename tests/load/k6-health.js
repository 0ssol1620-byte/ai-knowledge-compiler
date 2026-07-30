import http from "k6/http";
import { check } from "k6";

function boundedInteger(name, fallback, minimum, maximum) {
  const raw = __ENV[name] || String(fallback);
  const value = Number.parseInt(raw, 10);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return value;
}

const baseUrl = (__ENV.AKC_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const parsed = new URL(baseUrl);
const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
if (!localHosts.has(parsed.hostname)) {
  if (parsed.protocol !== "https:" || __ENV.AKC_ALLOW_REMOTE_SYNTHETIC !== "true") {
    throw new Error("remote targets require HTTPS and AKC_ALLOW_REMOTE_SYNTHETIC=true");
  }
}

export const options = {
  scenarios: {
    health: {
      executor: "constant-arrival-rate",
      rate: boundedInteger("AKC_REQUEST_RATE", 2, 1, 100),
      timeUnit: "1s",
      duration: `${boundedInteger("AKC_DURATION_SECONDS", 30, 10, 900)}s`,
      preAllocatedVUs: boundedInteger("AKC_PREALLOCATED_VUS", 2, 1, 50),
      maxVUs: boundedInteger("AKC_MAX_VUS", 10, 1, 100),
    },
  },
  thresholds: {
    checks: ["rate>0.999"],
    http_req_failed: ["rate<0.005"],
    "http_req_duration{endpoint:live}": ["p(95)<250"],
    "http_req_duration{endpoint:ready}": ["p(95)<500"],
    dropped_iterations: ["count==0"],
  },
  discardResponseBodies: true,
};

export default function () {
  const live = http.get(`${baseUrl}/health/live`, { tags: { endpoint: "live" } });
  check(live, { "liveness is 200": (response) => response.status === 200 });

  const ready = http.get(`${baseUrl}/health/ready`, { tags: { endpoint: "ready" } });
  check(ready, { "readiness is 200": (response) => response.status === 200 });
}
