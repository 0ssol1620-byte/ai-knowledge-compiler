/**
 * The R2 binding the Foundation CDR worker expects (get / list / put with create-once), served by
 * the disposable SeaweedFS S3 of the joined E2E. SIMULATED: this is not Cloudflare R2 and not the
 * workerd binding, only the same three calls over SigV4 against an S3-compatible store.
 */
import { createHash, createHmac } from "node:crypto";
import http from "node:http";

const sha256Hex = body => createHash("sha256").update(body).digest("hex");
const hmac = (key, body) => createHmac("sha256", key).update(body).digest();
// RFC 3986 unreserved characters stay; everything else is percent-encoded (AWS SigV4 rules).
const encode = value => encodeURIComponent(value).replace(/[!'()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
export const encodePath = path => path.split("/").map(encode).join("/");

/** AWS Signature Version 4 header signing. `headers` must already hold every header to sign, host included. */
export function signV4({ method, path, query = {}, headers, payloadSha256, accessKey, secretKey, region, service = "s3", amzDate }) {
  const lower = Object.fromEntries(Object.entries(headers).map(([name, value]) => [name.toLowerCase(), String(value).trim()]));
  const names = Object.keys(lower).sort();
  const canonicalQuery = Object.keys(query).sort().map(key => `${encode(key)}=${encode(query[key])}`).join("&");
  const canonical = [method, encodePath(path), canonicalQuery, names.map(name => `${name}:${lower[name]}\n`).join(""), names.join(";"), payloadSha256].join("\n");
  const day = amzDate.slice(0, 8), scope = `${day}/${region}/${service}/aws4_request`;
  const key = hmac(hmac(hmac(hmac(`AWS4${secretKey}`, day), region), service), "aws4_request");
  const signature = createHmac("sha256", key).update(`AWS4-HMAC-SHA256\n${amzDate}\n${scope}\n${sha256Hex(canonical)}`).digest("hex");
  return `AWS4-HMAC-SHA256 Credential=${accessKey}/${scope}, SignedHeaders=${names.join(";")}, Signature=${signature}`;
}

const xmlText = value => value.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&apos;/g, "'").replace(/&amp;/g, "&");

/**
 * endpoint: http://127.0.0.1:<port> of SeaweedFS; signedHost: the R2 host name SeaweedFS was told is its
 * external URL, restored as Host exactly like the Foundation gateway does for browser and Next traffic.
 */
export function s3Bucket({ endpoint, bucket, accessKey, secretKey, signedHost, region = "auto" }) {
  const target = new URL(endpoint);
  const send = (method, key, { query = {}, body = Buffer.alloc(0), extra = {} } = {}) => new Promise((resolve, reject) => {
    const path = `/${bucket}${key === null ? "" : `/${key}`}`;
    const amzDate = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
    const payloadSha256 = sha256Hex(body);
    const headers = { host: signedHost, "x-amz-content-sha256": payloadSha256, "x-amz-date": amzDate, ...extra };
    if (method === "PUT") headers["content-length"] = String(body.length);
    headers.authorization = signV4({ method, path, query, headers, payloadSha256, accessKey, secretKey, region, amzDate });
    const search = Object.keys(query).sort().map(name => `${encode(name)}=${encode(query[name])}`).join("&");
    const request = http.request({ hostname: target.hostname, port: target.port, method, path: `${encodePath(path)}${search ? `?${search}` : ""}`, headers, agent: false, timeout: 60_000 }, response => {
      const chunks = [];
      response.on("data", chunk => chunks.push(chunk));
      response.on("end", () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) }));
      response.on("error", reject);
    });
    request.on("timeout", () => request.destroy(new Error(`S3 ${method} timed out`)));
    request.on("error", reject);
    request.end(body);
  });
  const fail = (operation, result) => new Error(`S3 ${operation} returned HTTP ${result.status}: ${result.body.toString("utf8").slice(0, 300)}`);
  return {
    async get(key) {
      const result = await send("GET", key);
      if (result.status === 404) return null;
      if (result.status !== 200) throw fail("GET", result);
      const customMetadata = Object.fromEntries(Object.entries(result.headers)
        .filter(([name]) => name.startsWith("x-amz-meta-")).map(([name, value]) => [name.slice("x-amz-meta-".length), String(value)]));
      const bytes = result.body;
      return {
        size: bytes.length,
        httpMetadata: { contentType: result.headers["content-type"], contentDisposition: result.headers["content-disposition"] },
        customMetadata,
        arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
      };
    },
    async list({ prefix = "" } = {}) {
      const result = await send("GET", null, { query: { "list-type": "2", prefix } });
      if (result.status !== 200) throw fail("LIST", result);
      const xml = result.body.toString("utf8");
      // ponytail: one page only; the worker lists one document's prefix (a handful of keys). Paginate if that grows.
      if (/<IsTruncated>true<\/IsTruncated>/.test(xml)) throw new Error("S3 LIST was truncated; the harness adapter reads one page only");
      return { objects: [...xml.matchAll(/<Key>([^<]*)<\/Key>/g)].map(match => ({ key: xmlText(match[1]) })) };
    },
    async put(key, value, options = {}) {
      const body = typeof value === "string" ? Buffer.from(value) : Buffer.from(value instanceof ArrayBuffer ? new Uint8Array(value) : new Uint8Array(value.buffer, value.byteOffset, value.byteLength));
      const extra = {};
      if (options.httpMetadata?.contentType) extra["content-type"] = options.httpMetadata.contentType;
      for (const [name, metaValue] of Object.entries(options.customMetadata ?? {})) extra[`x-amz-meta-${name.toLowerCase()}`] = String(metaValue);
      const condition = options.onlyIf?.etagDoesNotMatch;
      if (condition !== undefined && condition !== "*") throw new Error("harness adapter models only onlyIf.etagDoesNotMatch \"*\"");
      if (condition === "*") extra["if-none-match"] = "*";
      const result = await send("PUT", key, { body, extra });
      if (result.status === 412) return null; // R2 returns null when a create-once precondition fails
      if (result.status !== 200) throw fail("PUT", result);
      return { key, size: body.length };
    },
  };
}
