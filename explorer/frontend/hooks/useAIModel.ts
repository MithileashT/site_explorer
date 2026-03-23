"use client";

import { useEffect, useRef } from "react";
import { useAIModelStore } from "@/lib/stores/ai-model-store";
import { getAIProviders, setAIProvider } from "@/lib/api";
import type { AIModelPageKey } from "@/lib/stores/ai-model-store";

/**
 * Central hook for AI model management.
 *
 * - Fetches providers once per app session (guarded by a store-level check).
 * - Exposes helpers to switch the global model or set / clear page overrides.
 * - Pass the caller's `pageKey` to get the effective model and override helpers.
 *
 * @example
 * // Global (Dashboard)
 * const { providers, globalModel, switchGlobalModel } = useAIModel();
 *
 * // Per-page
 * const { providers, effective, hasOverride, overridePage, clearOverride, switchGlobalModel } =
 *   useAIModel("bags");
 */
export function useAIModel(pageKey?: AIModelPageKey) {
  const {
    providers,
    setProviders,
    globalModel,
    setGlobalModel,
    pageOverrides,
    setPageOverride,
    clearPageOverride,
    effectiveModel,
  } = useAIModelStore();

  // Fetch providers exactly once per session (skipped if already populated).
  const hasFetched = useRef(false);
  useEffect(() => {
    if (hasFetched.current || providers.length > 0) return;
    hasFetched.current = true;
    getAIProviders()
      .then((resp) => {
        setProviders(resp.providers);
        // Seed globalModel from backend's active provider only if not yet set
        if (!globalModel) {
          setGlobalModel(resp.active.id);
        }
      })
      .catch(() => {
        // Silently ignore — UI will show "No models" in the selector
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * Switch the global model.
   * Calls the backend, updates the store on success.
   * Throws on failure so callers (ModelSelector) can surface an error message.
   */
  async function switchGlobalModel(id: string): Promise<void> {
    const resp = await setAIProvider(id);
    setProviders(resp.providers);
    setGlobalModel(resp.active.id);
  }

  /**
   * Set a page-level override.
   * Switches the backend immediately so the next AI call uses the override.
   * Throws on failure — caller should handle / revert.
   */
  async function overridePage(id: string): Promise<void> {
    if (!pageKey) return;
    const resp = await setAIProvider(id);
    setProviders(resp.providers);
    setPageOverride(pageKey, resp.active.id);
  }

  /** Clear the page-level override and restore the global model on the backend. */
  async function clearOverride(): Promise<void> {
    if (!pageKey) return;
    clearPageOverride(pageKey);
    // Restore global model on backend if one is set
    if (globalModel) {
      try {
        await setAIProvider(globalModel);
      } catch {
        // Non-fatal — state is already cleared locally
      }
    }
  }

  const activeOverride = pageKey ? (pageOverrides[pageKey] ?? null) : null;
  const effective = pageKey ? effectiveModel(pageKey) : globalModel;
  const hasOverride = !!activeOverride;

  return {
    providers,
    globalModel,
    effective,
    hasOverride,
    activeOverride,
    switchGlobalModel,
    overridePage,
    clearOverride,
  };
}
