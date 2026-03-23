/**
 * Unit tests for all Zustand store reset actions and the global resetAllStores().
 *
 * Run: npx vitest run tests/stores/reset.test.ts
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useAIModelStore } from "../../lib/stores/ai-model-store";
import { useAssistantStore } from "../../lib/stores/assistant-store";
import { useBagsStore } from "../../lib/stores/bags-store";
import { useInvestigateStore } from "../../lib/stores/investigate-store";
import { useSitemapStore } from "../../lib/stores/sitemap-store";
import { useSlackInvestigationStore } from "../../lib/stores/slack-investigation-store";
import { resetAllStores, logReset } from "../../lib/stores/reset-all";

// ── helpers ──────────────────────────────────────────────────────────────────

/** Grab the current values of all stores in one object for assertion. */
function snapshot() {
  return {
    bags: {
      bagPath: useBagsStore.getState().bagPath,
      tab: useBagsStore.getState().tab,
      bagSource: useBagsStore.getState().bagSource,
    },
    investigate: {
      env: useInvestigateStore.getState().env,
      selectedSite: useInvestigateStore.getState().selectedSite,
      searchText: useInvestigateStore.getState().searchText,
      allLines: useInvestigateStore.getState().allLines,
    },
    sitemap: {
      siteId: useSitemapStore.getState().siteId,
      meta: useSitemapStore.getState().meta,
      trajectory: useSitemapStore.getState().trajectory,
    },
    slack: {
      result: useSlackInvestigationStore.getState().result,
      sites: useSlackInvestigationStore.getState().sites,
    },
    assistant: {
      input: useAssistantStore.getState().input,
    },
  };
}

// ── per-store reset tests ─────────────────────────────────────────────────────

describe("useBagsStore.resetBags()", () => {
  beforeEach(() => {
    useBagsStore.setState({ bagPath: "/tmp/foo.bag", tab: "mapdiff", bagSource: "rio" });
  });

  it("clears bagPath to null", () => {
    useBagsStore.getState().resetBags();
    expect(useBagsStore.getState().bagPath).toBeNull();
  });

  it("resets tab to 'logs'", () => {
    useBagsStore.getState().resetBags();
    expect(useBagsStore.getState().tab).toBe("logs");
  });

  it("resets bagSource to 'upload'", () => {
    useBagsStore.getState().resetBags();
    expect(useBagsStore.getState().bagSource).toBe("upload");
  });

  it("clears timeline and analysis (in-memory)", () => {
    useBagsStore.setState({ timeline: { bag_path: "/foo", buckets: [] }, analysis: null });
    useBagsStore.getState().resetBags();
    expect(useBagsStore.getState().timeline).toBeNull();
    expect(useBagsStore.getState().analysis).toBeNull();
  });

  it("is stable across multiple consecutive resets", () => {
    for (let i = 0; i < 5; i++) {
      useBagsStore.setState({ bagPath: `/tmp/${i}.bag` });
      useBagsStore.getState().resetBags();
    }
    expect(useBagsStore.getState().bagPath).toBeNull();
  });
});

describe("useInvestigateStore.resetInvestigate()", () => {
  beforeEach(() => {
    useInvestigateStore.setState({
      selectedSite: "site-abc",
      searchText: "ERROR",
      allLines: [{ ts: "1000000000", line: "error log", labels: {} }],
      totalCount: 999,
      volumeData: [{ ts: 1, label: "00:01", count: 5 }],
      analysisResult: { summary: "blah", recommendations: [] } as never,
    });
  });

  it("clears selectedSite", () => {
    useInvestigateStore.getState().resetInvestigate();
    expect(useInvestigateStore.getState().selectedSite).toBe("");
  });

  it("clears searchText", () => {
    useInvestigateStore.getState().resetInvestigate();
    expect(useInvestigateStore.getState().searchText).toBe("");
  });

  it("clears allLines", () => {
    useInvestigateStore.getState().resetInvestigate();
    expect(useInvestigateStore.getState().allLines).toEqual([]);
  });

  it("clears totalCount to 0", () => {
    useInvestigateStore.getState().resetInvestigate();
    expect(useInvestigateStore.getState().totalCount).toBe(0);
  });

  it("clears volumeData", () => {
    useInvestigateStore.getState().resetInvestigate();
    expect(useInvestigateStore.getState().volumeData).toEqual([]);
  });

  it("clears analysisResult", () => {
    useInvestigateStore.getState().resetInvestigate();
    expect(useInvestigateStore.getState().analysisResult).toBeNull();
  });

  it("preserves default env value", () => {
    useInvestigateStore.setState({ env: "custom-env" });
    useInvestigateStore.getState().resetInvestigate();
    expect(useInvestigateStore.getState().env).toBe("sootballs-prod-logs-loki-US-latest");
  });

  it("is stable across multiple consecutive resets", () => {
    for (let i = 0; i < 5; i++) {
      useInvestigateStore.setState({ selectedSite: `site-${i}`, searchText: `text-${i}` });
      useInvestigateStore.getState().resetInvestigate();
    }
    expect(useInvestigateStore.getState().selectedSite).toBe("");
    expect(useInvestigateStore.getState().searchText).toBe("");
  });
});

describe("useSitemapStore.resetSitemap()", () => {
  beforeEach(() => {
    useSitemapStore.setState({
      siteId: "site-xyz",
      trajectory: [{ x: 1, y: 2, timestamp: 1000 }] as never,
      searchQuery: "rack-1",
      hiddenSpotTypes: ["idle_spot"],
      hiddenRegionTypes: ["aisle"],
    });
  });

  it("clears siteId", () => {
    useSitemapStore.getState().resetSitemap();
    expect(useSitemapStore.getState().siteId).toBe("");
  });

  it("clears trajectory", () => {
    useSitemapStore.getState().resetSitemap();
    expect(useSitemapStore.getState().trajectory).toEqual([]);
  });

  it("clears searchQuery", () => {
    useSitemapStore.getState().resetSitemap();
    expect(useSitemapStore.getState().searchQuery).toBe("");
  });

  it("clears hiddenSpotTypes and hiddenRegionTypes", () => {
    useSitemapStore.getState().resetSitemap();
    expect(useSitemapStore.getState().hiddenSpotTypes).toEqual([]);
    expect(useSitemapStore.getState().hiddenRegionTypes).toEqual([]);
  });

  it("restores default layers (all true)", () => {
    useSitemapStore.setState({ layers: { spots: false, racks: false, regions: false, markers: false, nodes: false } });
    useSitemapStore.getState().resetSitemap();
    const { layers } = useSitemapStore.getState();
    expect(layers.spots).toBe(true);
    expect(layers.racks).toBe(true);
    expect(layers.regions).toBe(true);
    expect(layers.markers).toBe(true);
    expect(layers.nodes).toBe(true);
  });
});

describe("useSlackInvestigationStore.resetSlackInvestigation()", () => {
  beforeEach(() => {
    useSlackInvestigationStore.setState({
      result: { analysis: "something" } as never,
      sites: [{ id: "s1", name: "Site 1" }],
      providers: [{ id: "openai", label: "OpenAI", available: true }] as never,
    });
  });

  it("clears result", () => {
    useSlackInvestigationStore.getState().resetSlackInvestigation();
    expect(useSlackInvestigationStore.getState().result).toBeNull();
  });

  it("clears sites", () => {
    useSlackInvestigationStore.getState().resetSlackInvestigation();
    expect(useSlackInvestigationStore.getState().sites).toEqual([]);
  });

  it("clears providers", () => {
    useSlackInvestigationStore.getState().resetSlackInvestigation();
    expect(useSlackInvestigationStore.getState().providers).toEqual([]);
  });

  it("clears activeProvider", () => {
    useSlackInvestigationStore.setState({ activeProvider: { id: "openai" } as never });
    useSlackInvestigationStore.getState().resetSlackInvestigation();
    expect(useSlackInvestigationStore.getState().activeProvider).toBeNull();
  });
});

describe("useAssistantStore.resetAssistant()", () => {
  beforeEach(() => {
    useAssistantStore.setState({ input: "some typed text", messages: [] });
  });

  it("clears input", () => {
    useAssistantStore.getState().resetAssistant();
    expect(useAssistantStore.getState().input).toBe("");
  });

  it("restores welcome message", () => {
    useAssistantStore.getState().resetAssistant();
    const msgs = useAssistantStore.getState().messages;
    expect(msgs.length).toBe(1);
    expect(msgs[0].role).toBe("system");
  });
});

// ── global reset ──────────────────────────────────────────────────────────────

describe("resetAllStores()", () => {
  beforeEach(() => {
    // Set dirty state across every store
    useAIModelStore.setState({ globalModel: "dirty-model", pageOverrides: { bags: "override-m" } });
    useBagsStore.setState({ bagPath: "/dirty.bag", bagSource: "device" });
    useInvestigateStore.setState({ selectedSite: "dirty-site", searchText: "dirty" });
    useSitemapStore.setState({ siteId: "dirty-site", searchQuery: "dirty" });
    useSlackInvestigationStore.setState({ sites: [{ id: "d", name: "Dirty" }] });
    useAssistantStore.setState({ input: "dirty input" });
    // Simulate persisted sessionStorage entries
    sessionStorage.setItem("amr-ai-model-state", JSON.stringify({ globalModel: "dirty-model" }));
    sessionStorage.setItem("amr-bags-state", JSON.stringify({ bagPath: "/dirty.bag" }));
    sessionStorage.setItem("amr-investigate-state", JSON.stringify({ selectedSite: "dirty-site" }));
    sessionStorage.setItem("amr-sitemap-state", JSON.stringify({ siteId: "dirty-site" }));
    sessionStorage.setItem("amr-slack-investigation-state", "{}");
    sessionStorage.setItem("amr-assistant-state", JSON.stringify({ input: "dirty" }));
  });

  it("resets bags store", () => {
    resetAllStores();
    expect(useBagsStore.getState().bagPath).toBeNull();
    expect(useBagsStore.getState().bagSource).toBe("upload");
  });

  it("resets investigate store", () => {
    resetAllStores();
    expect(useInvestigateStore.getState().selectedSite).toBe("");
    expect(useInvestigateStore.getState().searchText).toBe("");
  });

  it("resets sitemap store", () => {
    resetAllStores();
    expect(useSitemapStore.getState().siteId).toBe("");
    expect(useSitemapStore.getState().searchQuery).toBe("");
  });

  it("resets slack investigation store", () => {
    resetAllStores();
    expect(useSlackInvestigationStore.getState().sites).toEqual([]);
  });

  it("resets assistant store", () => {
    resetAllStores();
    expect(useAssistantStore.getState().input).toBe("");
  });

  it("resets AI model store globalModel", () => {
    resetAllStores();
    expect(useAIModelStore.getState().globalModel).toBeNull();
  });

  it("resets AI model store pageOverrides", () => {
    resetAllStores();
    expect(useAIModelStore.getState().pageOverrides).toEqual({});
  });

  it("clears all sessionStorage keys", () => {
    resetAllStores();
    expect(sessionStorage.getItem("amr-ai-model-state")).toBeNull();
    expect(sessionStorage.getItem("amr-bags-state")).toBeNull();
    expect(sessionStorage.getItem("amr-investigate-state")).toBeNull();
    expect(sessionStorage.getItem("amr-sitemap-state")).toBeNull();
    expect(sessionStorage.getItem("amr-slack-investigation-state")).toBeNull();
    expect(sessionStorage.getItem("amr-assistant-state")).toBeNull();
  });

  it("does not corrupt unrelated sessionStorage keys", () => {
    sessionStorage.setItem("sidebar-pinned", "true");
    resetAllStores();
    expect(sessionStorage.getItem("sidebar-pinned")).toBe("true");
  });

  it("is idempotent — second call produces the same clean state", () => {
    resetAllStores();
    const first = snapshot();
    resetAllStores();
    const second = snapshot();
    expect(second).toEqual(first);
  });

  it("handles reset during 'active operation' state without throwing", () => {
    // Simulate loading state in investigate store
    useInvestigateStore.setState({ allLines: [{ ts: "999", line: "log", labels: {} }] });
    expect(() => resetAllStores()).not.toThrow();
    expect(useInvestigateStore.getState().allLines).toEqual([]);
  });

  it("handles empty/partial state gracefully", () => {
    // Stores already cleared — reset again should not throw
    useBagsStore.setState({ bagPath: null });
    expect(() => resetAllStores()).not.toThrow();
  });
});

// ── logReset ──────────────────────────────────────────────────────────────────

describe("logReset()", () => {
  it("logs 'Global' for scope='global'", () => {
    const spy = vi.spyOn(console, "info").mockImplementation(() => {});
    logReset("global");
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("[AMR Reset] Global"));
    spy.mockRestore();
  });

  it("logs page name for page-level scope", () => {
    const spy = vi.spyOn(console, "info").mockImplementation(() => {});
    logReset("bags");
    expect(spy).toHaveBeenCalledWith(expect.stringContaining("Page: bags"));
    spy.mockRestore();
  });

  it("includes timestamp in log output", () => {
    const spy = vi.spyOn(console, "info").mockImplementation(() => {});
    logReset("investigate");
    expect(spy).toHaveBeenCalledWith(expect.stringMatching(/timestamp=\d{4}-\d{2}-\d{2}/));
    spy.mockRestore();
  });
});
