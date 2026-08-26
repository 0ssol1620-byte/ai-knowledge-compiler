import { createCipheriv, createDecipheriv, createHash, randomBytes } from "crypto";
import { ENV } from "./_core/env";

/** Tokens never leave the server after an OAuth callback. The key is derived from the managed session secret. */
function tokenKey() {
  if (!ENV.cookieSecret) throw new Error("Connector token encryption is unavailable.");
  return createHash("sha256").update(`tavonel:connector-tokens:v1:${ENV.cookieSecret}`).digest();
}

export function encryptConnectorToken(value: string) {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", tokenKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(value, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, ciphertext]).toString("base64url");
}

export function decryptConnectorToken(payload: string) {
  const bytes = Buffer.from(payload, "base64url");
  const iv = bytes.subarray(0, 12);
  const tag = bytes.subarray(12, 28);
  const ciphertext = bytes.subarray(28);
  const decipher = createDecipheriv("aes-256-gcm", tokenKey(), iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
}
