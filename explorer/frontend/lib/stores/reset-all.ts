/**
 * Global reset utility — resets ALL page stores and wipes sessionStorage
 * so a subsequent browser refresh also starts clean.
 *
 * Usage (sidebar):
 *   import { resetAllStores } from "@/lib/stores/reset-all";
 *   resetAllStores();
 *
 * Usage (page-level logging):
 *   import { logReset } from "@/lib/stores/reset-all";
 *   logReset("bags");     // emits "[AMR Reset] Page: bags  …"
 *   logReset("global");   // emits "[AMR Reset] Global  …"
 */

import { useAIModelStore } from "./ai-model-store";
import { useAssistantStore } from "./assistant-store";
import { useBagsStore } from "./bags-store";
import { useInvestigateStore } from "./investigate-store";
import { useSitemapStore } from "./sitemap-store";
import { useSlackInvestigationStore } from "./slack-investigation-store";

/** Keys written by Zustand persist middleware — cleared on global reset. */
const SESSION_STORAGE_KEYS = [
  "amr-ai-model-state",
  "amr-assistant-state",
  "amr-bags-state",
  "amr-investigate-state",
  "amr-sitemap-state",
  "amr-slack-investigation-state",
] as const;

/**
 * Structured console logger for reset actions.
 * @param scope "global" | page name (e.g. "bags", "investigate", …)
 */
export function logReset(scope: "global" | string): void {
  const label = scope === "global" ? "Global" : `Page: ${scope}`;
  console.info(
    `[AMR Reset] ${label}  timestamp=${new Date().toISOString()}  stores=${scope === "global" ? "ALL" : scope}`
  );
}

/**
 * Resets every store in the application AND removes all persisted
 * sessionStorage keys so a hard browser refresh also loads clean defaults.
 *
 * This is the handler for the global "Reset All" button in the Sidebar.
 */
export function resetAllStores(): void {
  logReset("global");

  // Reset each store's in-memory Zustand state
  useAIModelStore.getState().resetAIModel();
  useAssistantStore.getState().resetAssistant();
  useBagsStore.getState().resetBags();
  useInvestigateStore.getState().resetInvestigate();
  useSitemapStore.getState().resetSitemap();
  useSlackInvestigationStore.getState().resetSlackInvestigation();

  // Wipe the sessionStorage entries so browser refresh starts clean
  if (typeof sessionStorage !== "undefined") {
    SESSION_STORAGE_KEYS.forEach((key) => sessionStorage.removeItem(key));
  }
}
