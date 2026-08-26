import { describe, expect, it } from "vitest";
import { createEnrollmentSecret, enrollmentCredential, enrollmentHashMatches, hashEnrollmentSecret, normalizeAgentRoots, parseEnrollmentCredential } from "./fileServerAgentProtocol";

describe("file server agent protocol", () => {
  it("normalizes customer-selected roots and rejects empty selections", () => {
    expect(normalizeAgentRoots([" C:\\Research\\ ", "/srv/knowledge/"])).toEqual(["C:/Research", "/srv/knowledge"]);
    expect(() => normalizeAgentRoots(["   "])).toThrow("Choose at least one");
  });

  it("returns a parseable credential while storing only its hash", () => {
    const secret = createEnrollmentSecret();
    const credential = enrollmentCredential(42, secret);
    expect(parseEnrollmentCredential(credential)).toEqual({ agentId: 42, secret });
    expect(enrollmentHashMatches(secret, hashEnrollmentSecret(secret))).toBe(true);
    expect(enrollmentHashMatches("incorrect-agent-secret", hashEnrollmentSecret(secret))).toBe(false);
  });
});
