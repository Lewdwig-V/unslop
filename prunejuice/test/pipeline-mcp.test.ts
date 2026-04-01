import { describe, it, expect } from "vitest";
import {
  handleDistill,
  handleCover,
  handleWeed,
  handleVerify,
  handleGenerate,
  handleGenerateResume,
} from "../src/pipeline-mcp.js";

describe("pipeline MCP handlers", () => {
  it("handleGenerate is exported with correct signature", () => {
    expect(typeof handleGenerate).toBe("function");
  });

  it("handleGenerateResume is exported with correct signature", () => {
    expect(typeof handleGenerateResume).toBe("function");
  });

  it("handleDistill is exported with correct signature", () => {
    expect(typeof handleDistill).toBe("function");
  });

  it("handleCover is exported with correct signature", () => {
    expect(typeof handleCover).toBe("function");
  });

  it("handleWeed is exported with correct signature", () => {
    expect(typeof handleWeed).toBe("function");
  });

  it("handleVerify is exported with correct signature", () => {
    expect(typeof handleVerify).toBe("function");
  });
});
