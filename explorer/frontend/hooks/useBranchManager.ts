import { useState, useEffect, useCallback, useRef } from "react";
import type { BranchInfo } from "@/lib/types";
import {
  getSiteBranchInfo,
  setSiteBranch,
  clearSiteBranch,
  syncSiteRepo,
} from "@/lib/api";

/**
 * Manages git branch state for a given site: initial load, switching,
 * clearing overrides, syncing from remote, and manual refresh.
 */
export function useBranchManager(siteId: string) {
  const [branchInfo, setBranchInfo] = useState<BranchInfo | null>(null);
  const [syncing, setSyncing] = useState(false);

  // Keep a stable ref to setBranchInfo so callbacks don't go stale.
  const setBranchInfoRef = useRef(setBranchInfo);
  useEffect(() => { setBranchInfoRef.current = setBranchInfo; });

  // Reload branch info whenever siteId changes.
  useEffect(() => {
    if (!siteId) { setBranchInfo(null); return; }
    setBranchInfo(null);
    getSiteBranchInfo(siteId)
      .then(setBranchInfo)
      .catch(() => setBranchInfo(null));
  }, [siteId]);

  /** Re-fetches branch info for the current (or specified) site. */
  const refreshBranchInfo = useCallback(async (id?: string) => {
    const target = id ?? siteId;
    if (!target) return;
    try {
      const info = await getSiteBranchInfo(target);
      setBranchInfoRef.current(info);
    } catch {
      setBranchInfoRef.current(null);
    }
  }, [siteId]);

  /** Pin a specific branch for this site and update internal state. */
  const handleSetBranch = useCallback(async (branch: string) => {
    const updated = await setSiteBranch(siteId, branch);
    setBranchInfo(updated);
  }, [siteId]);

  /** Remove the branch override (revert to auto-detect). */
  const handleClearBranch = useCallback(async () => {
    const updated = await clearSiteBranch(siteId);
    setBranchInfo(updated);
  }, [siteId]);

  /**
   * Run git fetch then reload branch info.
   * Returns true on success, false if the sync failed.
   */
  const handleSync = useCallback(async (): Promise<boolean> => {
    if (!siteId) return false;
    setSyncing(true);
    try {
      await syncSiteRepo();
      const info = await getSiteBranchInfo(siteId);
      setBranchInfo(info);
      return true;
    } catch {
      return false;
    } finally {
      setSyncing(false);
    }
  }, [siteId]);

  return {
    branchInfo,
    setBranchInfo,
    syncing,
    refreshBranchInfo,
    handleSetBranch,
    handleClearBranch,
    handleSync,
  };
}
