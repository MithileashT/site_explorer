import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type { AIProviderInfo } from "@/lib/types";

export type AIModelPageKey = "bags" | "investigate" | "slack-investigation" | "assistant";

interface AIModelState {
  /** Shared provider catalogue — fetched once on mount, stored here */
  providers: AIProviderInfo[];
  /** The globally selected model id (null = use whatever backend reports as active) */
  globalModel: string | null;
  /** Per-page overrides. A missing / undefined entry means "use global". */
  pageOverrides: Partial<Record<AIModelPageKey, string>>;

  // Actions
  setProviders: (p: AIProviderInfo[]) => void;
  setGlobalModel: (id: string | null) => void;
  setPageOverride: (page: AIModelPageKey, id: string) => void;
  clearPageOverride: (page: AIModelPageKey) => void;
  /** Returns the effective model id for the given page: override ?? global ?? null */
  effectiveModel: (page: AIModelPageKey) => string | null;
  resetAIModel: () => void;
}

const initialState = {
  providers: [] as AIProviderInfo[],
  globalModel: null as string | null,
  pageOverrides: {} as Partial<Record<AIModelPageKey, string>>,
};

export const useAIModelStore = create<AIModelState>()(
  devtools(
    persist(
      (set, get) => ({
        ...initialState,

        setProviders: (p) => set({ providers: p }),

        setGlobalModel: (id) => set({ globalModel: id }),

        setPageOverride: (page, id) =>
          set((s) => ({ pageOverrides: { ...s.pageOverrides, [page]: id } })),

        clearPageOverride: (page) =>
          set((s) => {
            const next = { ...s.pageOverrides };
            delete next[page];
            return { pageOverrides: next };
          }),

        effectiveModel: (page) => {
          const s = get();
          return s.pageOverrides[page] ?? s.globalModel ?? null;
        },

        resetAIModel: () => set(initialState),
      }),
      {
        name: "amr-ai-model-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
        // providers are NOT persisted — always re-fetched fresh on mount
        partialize: (state) => ({
          globalModel: state.globalModel,
          pageOverrides: state.pageOverrides,
        }),
      }
    ),
    { name: "AIModelStore", enabled: process.env.NODE_ENV === "development" }
  )
);
