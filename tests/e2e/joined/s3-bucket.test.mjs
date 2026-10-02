// node --test tests/e2e/joined/s3-bucket.test.mjs -- SigV4 against the worked examples in the AWS S3
// "Signature Calculations for the Authorization Header" documentation.
import assert from "node:assert/strict";
import test from "node:test";
import { signV4 } from "./s3-bucket.mjs";

const credentials = { accessKey: "AKIAIOSFODNN7EXAMPLE", secretKey: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", region: "us-east-1", amzDate: "20130524T000000Z" };
const empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const host = "examplebucket.s3.amazonaws.com";
const signatureOf = header => /Signature=([0-9a-f]{64})$/.exec(header)[1];

test("GET object with a Range header", () => {
  const header = signV4({ ...credentials, method: "GET", path: "/test.txt", payloadSha256: empty,
    headers: { host, range: "bytes=0-9", "x-amz-content-sha256": empty, "x-amz-date": credentials.amzDate } });
  assert.equal(signatureOf(header), "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41");
  assert.match(header, /SignedHeaders=host;range;x-amz-content-sha256;x-amz-date,/);
});

test("GET bucket listing with a sorted query string", () => {
  const header = signV4({ ...credentials, method: "GET", path: "/", query: { prefix: "J", "max-keys": "2" }, payloadSha256: empty,
    headers: { host, "x-amz-content-sha256": empty, "x-amz-date": credentials.amzDate } });
  assert.equal(signatureOf(header), "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7");
});

test("PUT object whose key needs percent-encoding", () => {
  const payload = "44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072";
  const header = signV4({ ...credentials, method: "PUT", path: "/test$file.text", payloadSha256: payload,
    headers: { host, date: "Fri, 24 May 2013 00:00:00 GMT", "x-amz-date": credentials.amzDate, "x-amz-storage-class": "REDUCED_REDUNDANCY", "x-amz-content-sha256": payload } });
  assert.equal(signatureOf(header), "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd");
});

test("a wrong secret does not reproduce the documented signature", () => {
  const header = signV4({ ...credentials, secretKey: "not-the-example-secret", method: "GET", path: "/test.txt", payloadSha256: empty,
    headers: { host, range: "bytes=0-9", "x-amz-content-sha256": empty, "x-amz-date": credentials.amzDate } });
  assert.notEqual(signatureOf(header), "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41");
});
