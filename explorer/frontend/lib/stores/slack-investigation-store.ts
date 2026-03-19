import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type {
  SlackThreadInvestigationResponse,
  AIProviderInfo,
} from "@/lib/types";

interface SlackInvestigationState {
  result: SlackThreadInvestigationResponse | null;
  sites: { id: string; name: string }[];
  providers: AIProviderInfo[];
  activeProvider: AIProviderInfo | null;

  setResult: (r: SlackThreadInvestigationResponse | null) => void;
  setSites: (s: { id: string; name: string }[]) => void;
  setProviders: (p: AIProviderInfo[]) => void;
  setActiveProvider: (p: AIProviderInfo | null) => void;
  resetSlackInvestigation: () => void;
}

const initialState = {
  result: null as SlackThreadInvestigationResponse | null,
  sites: [] as { id: string; name: string }[],
  providers: [] as AIProviderInfo[],
  activeProvider: null as AIProviderInfo | null,
};

export const useSlackInvestigationStore = create<SlackInvestigationState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setResult: (r) => set({ result: r }),
        setSites: (s) => set({ sites: s }),
        setProviders: (p) => set({ providers: p }),
        setActiveProvider: (p) => set({ activeProvider: p }),
        resetSlackInvestigation: () => set(initialState),
      }),
      {
        name: "amr-slack-investigation-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
      }
    ),
    { name: "SlackInvestigationStore", enabled: process.env.NODE_ENV === "development" }
  )
);
