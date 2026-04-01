import { describe, it, expect } from "vitest";

describe("verify", () => {
  it("is exported from api.ts", async () => {
    const api = await import("../src/api.js");
    expect(typeof api.verify).toBe("function");
  });

  it("throws when spec artifact is missing", async () => {
    const { verify } = await import("../src/api.js");
    await expect(
      verify("/tmp/nonexistent-verify-test", {
        specPath: "test.spec.md",
        managedFilePath: "test.ts",
      }),
    ).rejects.toThrow();
  });
});
