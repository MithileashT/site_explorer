/**
 * Unit tests for useAIModelStore.
 *
 * Run: npx vitest run tests/stores/ai-model-store.test.ts
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useAIModelStore } from "../../lib/stores/ai-model-store";

describe("useAIModelStore", () => {
  beforeEach(() => {
    sessionStorage.clear();
    useAIModelStore.getState().resetAIModel();
  });

  // ── initial state ──────────────────────────────────────────────────────────

  it("has null globalModel by default", () => {
    expect(useAIModelStore.getState().globalModel).toBeNull();
  });

  it("has empty pageOverrides by default", () => {
    expect(useAIModelStore.getState().pageOverrides).toEqual({});
  });

  it("has empty providers list by default", () => {
    expect(useAIModelStore.getState().providers).toEqual([]);
  });

  // ── setGlobalModel ─────────────────────────────────────────────────────────

  it("setGlobalModel updates globalModel", () => {
    useAIModelStore.getState().setGlobalModel("openai-gpt4");
    expect(useAIModelStore.getState().globalModel).toBe("openai-gpt4");
  });

  it("setGlobalModel accepts null to clear the model", () => {
    useAIModelStore.getState().setGlobalModel("some-model");
    useAIModelStore.getState().setGlobalModel(null);
    expect(useAIModelStore.getState().globalModel).toBeNull();
  });

  // ── setPageOverride / clearPageOverride ────────────────────────────────────

  it("setPageOverride sets override for a specific page", () => {
    useAIModelStore.getState().setPageOverride("bags", "gemini-pro");
    expect(useAIModelStore.getState().pageOverrides.bags).toBe("gemini-pro");
  });

  it("setPageOverride does not affect other pages", () => {
    useAIModelStore.getState().setPageOverride("bags", "gemini-pro");
    expect(useAIModelStore.getState().pageOverrides["investigate"]).toBeUndefined();
  });

  it("clearPageOverride removes override for a page", () => {
    useAIModelStore.getState().setPageOverride("bags", "gemini-pro");
    useAIModelStore.getState().clearPageOverride("bags");
    expect(useAIModelStore.getState().pageOverrides.bags).toBeUndefined();
  });

  it("clearPageOverride on a page with no override does not throw", () => {
    expect(() => useAIModelStore.getState().clearPageOverride("assistant")).not.toThrow();
  });

  // ── effectiveModel ─────────────────────────────────────────────────────────

  it("effectiveModel returns pageOverride when set", () => {
    useAIModelStore.getState().setGlobalModel("global-model");
    useAIModelStore.getState().setPageOverride("investigate", "page-model");
    expect(useAIModelStore.getState().effectiveModel("investigate")).toBe("page-model");
  });

  it("effectiveModel falls back to globalModel when no override set", () => {
    useAIModelStore.getState().setGlobalModel("global-model");
    expect(useAIModelStore.getState().effectiveModel("bags")).toBe("global-model");
  });

  it("effectiveModel returns null when neither override nor global is set", () => {
    expect(useAIModelStore.getState().effectiveModel("bags")).toBeNull();
  });

  it("effectiveModel returns pageOverride even if global is also set", () => {
    useAIModelStore.getState().setGlobalModel("global");
    useAIModelStore.getState().setPageOverride("slack-investigation", "override");
    expect(useAIModelStore.getState().effectiveModel("slack-investigation")).toBe("override");
    // other pages still see global
    expect(useAIModelStore.getState().effectiveModel("bags")).toBe("global");
  });

  // ── setProviders ───────────────────────────────────────────────────────────

  it("setProviders stores the provider list", () => {
    const p = [{ id: "a", name: "A", type: "ollama" as const }];
    useAIModelStore.getState().setProviders(p);
    expect(useAIModelStore.getState().providers).toEqual(p);
  });

  it("setProviders overwrites previous list", () => {
    useAIModelStore.getState().setProviders([{ id: "a", name: "A", type: "ollama" as const }]);
    useAIModelStore.getState().setProviders([{ id: "b", name: "B", type: "openai" as const }]);
    expect(useAIModelStore.getState().providers).toHaveLength(1);
    expect(useAIModelStore.getState().providers[0].id).toBe("b");
  });

  // ── resetAIModel ───────────────────────────────────────────────────────────

  it("resetAIModel clears globalModel", () => {
    useAIModelStore.getState().setGlobalModel("x");
    useAIModelStore.getState().resetAIModel();
    expect(useAIModelStore.getState().globalModel).toBeNull();
  });

  it("resetAIModel clears all pageOverrides", () => {
    useAIModelStore.getState().setPageOverride("bags", "y");
    useAIModelStore.getState().setPageOverride("investigate", "z");
    useAIModelStore.getState().resetAIModel();
    expect(useAIModelStore.getState().pageOverrides).toEqual({});
  });

  it("resetAIModel clears providers", () => {
    useAIModelStore.getState().setProviders([{ id: "x", name: "X", type: "ollama" as const }]);
    useAIModelStore.getState().resetAIModel();
    expect(useAIModelStore.getState().providers).toEqual([]);
  });

  it("is idempotent across multiple resets", () => {
    for (let i = 0; i < 3; i++) {
      useAIModelStore.getState().setGlobalModel("m");
      useAIModelStore.getState().setPageOverride("bags", "n");
      useAIModelStore.getState().resetAIModel();
    }
    expect(useAIModelStore.getState().globalModel).toBeNull();
    expect(useAIModelStore.getState().pageOverrides).toEqual({});
  });
});
