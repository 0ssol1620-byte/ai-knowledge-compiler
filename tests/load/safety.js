export function guardedBaseUrl() {
  const baseUrl = (__ENV.AKC_BASE_URL || "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  );
  const parsed = new URL(baseUrl);
  const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
  const allowedOrigins = new Set(
    (__ENV.AKC_ALLOWED_REMOTE_ORIGINS || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean),
  );

  if (__ENV.AKC_LOAD_CONFIRM !== "NONPRODUCTION_LOAD_ONLY") {
    throw new Error("AKC_LOAD_CONFIRM=NONPRODUCTION_LOAD_ONLY is required");
  }
  if (
    !localHosts.has(parsed.hostname) &&
    (parsed.protocol !== "https:" ||
      __ENV.AKC_ALLOW_REMOTE_SYNTHETIC !== "true" ||
      !allowedOrigins.has(baseUrl))
  ) {
    throw new Error(
      "remote load requires HTTPS, AKC_ALLOW_REMOTE_SYNTHETIC=true, and an exact " +
        "AKC_ALLOWED_REMOTE_ORIGINS match",
    );
  }
  return baseUrl;
}

export function requireFixture(names) {
  for (const name of names) {
    if (!__ENV[name]) throw new Error(`${name} is required`);
  }
}

export function jsonHeaders(token, extra = {}) {
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}
