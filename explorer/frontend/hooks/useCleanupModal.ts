import { useState, useCallback } from "react";
import type { BranchCleanupPlan, BranchCleanupResult } from "@/lib/types";
import { getBranchCleanupPlan, runBranchCleanup } from "@/lib/api";

/** Manages the branch cleanup modal: fetching the plan and executing cleanup. */
export function useCleanupModal() {
  const [showCleanupModal, setShowCleanupModal] = useState(false);
  const [cleanupPlan, setCleanupPlan] = useState<BranchCleanupPlan | null>(null);
  const [cleanupResult, setCleanupResult] = useState<BranchCleanupResult | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupPlanLoading, setCleanupPlanLoading] = useState(false);
  const [cleanupErr, setCleanupErr] = useState("");

  /** Open the modal and fetch the cleanup dry-run plan. */
  const openCleanupModal = useCallback(async () => {
    setCleanupPlan(null);
    setCleanupResult(null);
    setCleanupErr("");
    setShowCleanupModal(true);
    setCleanupPlanLoading(true);
    try {
      const plan = await getBranchCleanupPlan();
      setCleanupPlan(plan);
    } catch (e: unknown) {
      setCleanupErr(e instanceof Error ? e.message : "Failed to load cleanup plan.");
    } finally {
      setCleanupPlanLoading(false);
    }
  }, []);

  /**
   * Execute the branch cleanup.
   * Optionally calls onDone() after a successful run (e.g. to refresh branch info).
   */
  const handleRunCleanup = useCallback(async (onDone?: () => void) => {
    setCleanupLoading(true);
    setCleanupErr("");
    try {
      const result = await runBranchCleanup();
      setCleanupResult(result);
      onDone?.();
    } catch (e: unknown) {
      setCleanupErr(e instanceof Error ? e.message : "Cleanup failed");
    } finally {
      setCleanupLoading(false);
    }
  }, []);

  return {
    showCleanupModal,
    setShowCleanupModal,
    cleanupPlan,
    cleanupResult,
    cleanupLoading,
    cleanupPlanLoading,
    cleanupErr,
    openCleanupModal,
    handleRunCleanup,
  };
}
