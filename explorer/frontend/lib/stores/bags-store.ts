import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type { BagLogAnalysisResponse, BagTimeline } from "@/lib/types";

type Tab = "logs" | "mapdiff";
type BagSource = "upload" | "rio" | "device";

interface BagsState {
  // Persisted (lightweight)
  bagPath: string | null;
  tab: Tab;
  bagSource: BagSource;

  // In-memory only (heavy — excluded from sessionStorage via partialize)
  timeline: BagTimeline | null;
  analysis: BagLogAnalysisResponse | null;

  setBagPath: (p: string | null) => void;
  setTimeline: (t: BagTimeline | null) => void;
  setAnalysis: (a: BagLogAnalysisResponse | null) => void;
  setTab: (t: Tab) => void;
  setBagSource: (s: BagSource) => void;
  resetBags: () => void;
}

const initialState = {
  bagPath: null as string | null,
  timeline: null as BagTimeline | null,
  analysis: null as BagLogAnalysisResponse | null,
  tab: "logs" as Tab,
  bagSource: "upload" as BagSource,
};

export const useBagsStore = create<BagsState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setBagPath: (p) => set({ bagPath: p }),
        setTimeline: (t) => set({ timeline: t }),
        setAnalysis: (a) => set({ analysis: a }),
        setTab: (t) => set({ tab: t }),
        setBagSource: (s) => set({ bagSource: s }),
        resetBags: () => set(initialState),
      }),
      {
        name: "amr-bags-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
        partialize: (state) => ({
          bagPath: state.bagPath,
          tab: state.tab,
          bagSource: state.bagSource,
        }),
      }
    ),
    { name: "BagsStore", enabled: process.env.NODE_ENV === "development" }
  )
);
