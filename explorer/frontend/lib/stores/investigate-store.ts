import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type { LokiLogLine, AnalyseResponse, AIProviderInfo } from "@/lib/types";

interface InvestigateState {
  // Persisted (lightweight filters & selections)
  env: string;
  selectedSite: string;
  siteOptions: string[];
  hostnameOptions: string[];
  selectedHostnames: string[];
  deploymentOptions: string[];
  selectedDeployments: string[];
  searchText: string;
  excludeText: string;
  fromDate: string;
  fromTime: string;
  toDate: string;
  toTime: string;
  activeQuick: string;
  issueDesc: string;
  providers: AIProviderInfo[];
  activeProvider: AIProviderInfo | null;

  // In-memory only (heavy — excluded from sessionStorage via partialize)
  allLines: LokiLogLine[];
  totalCount: number;
  volumeData: { ts: number; label: string; count: number }[];
  analysisResult: AnalyseResponse | null;

  // Actions
  setEnv: (e: string) => void;
  setSelectedSite: (s: string) => void;
  setSiteOptions: (o: string[]) => void;
  setHostnameOptions: (o: string[]) => void;
  setSelectedHostnames: (h: string[]) => void;
  setDeploymentOptions: (o: string[]) => void;
  setSelectedDeployments: (d: string[]) => void;
  setSearchText: (t: string) => void;
  setExcludeText: (t: string) => void;
  setFromDate: (d: string) => void;
  setFromTime: (t: string) => void;
  setToDate: (d: string) => void;
  setToTime: (t: string) => void;
  setActiveQuick: (q: string) => void;
  setAllLines: (l: LokiLogLine[]) => void;
  setTotalCount: (c: number) => void;
  setVolumeData: (v: { ts: number; label: string; count: number }[]) => void;
  setIssueDesc: (d: string) => void;
  setAnalysisResult: (r: AnalyseResponse | null) => void;
  setProviders: (p: AIProviderInfo[]) => void;
  setActiveProvider: (p: AIProviderInfo | null) => void;
  resetInvestigate: () => void;
}

const now = Date.now();
function toDateStr(ms: number) { return new Date(ms).toISOString().slice(0, 10); }
function toTimeStr(ms: number) { return new Date(ms).toISOString().slice(11, 19); }

const initialState = {
  env: "sootballs-prod-logs-loki-US-latest",
  selectedSite: "",
  siteOptions: [] as string[],
  hostnameOptions: [] as string[],
  selectedHostnames: [] as string[],
  deploymentOptions: [] as string[],
  selectedDeployments: [] as string[],
  searchText: "",
  excludeText: "",
  fromDate: toDateStr(now - 15 * 60 * 1000),
  fromTime: toTimeStr(now - 15 * 60 * 1000),
  toDate: toDateStr(now),
  toTime: toTimeStr(now),
  activeQuick: "Last 15m",
  allLines: [] as LokiLogLine[],
  totalCount: 0,
  volumeData: [] as { ts: number; label: string; count: number }[],
  issueDesc: "",
  analysisResult: null as AnalyseResponse | null,
  providers: [] as AIProviderInfo[],
  activeProvider: null as AIProviderInfo | null,
};

export const useInvestigateStore = create<InvestigateState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setEnv: (e) => set({ env: e }),
        setSelectedSite: (s) => set({ selectedSite: s }),
        setSiteOptions: (o) => set({ siteOptions: o }),
        setHostnameOptions: (o) => set({ hostnameOptions: o }),
        setSelectedHostnames: (h) => set({ selectedHostnames: h }),
        setDeploymentOptions: (o) => set({ deploymentOptions: o }),
        setSelectedDeployments: (d) => set({ selectedDeployments: d }),
        setSearchText: (t) => set({ searchText: t }),
        setExcludeText: (t) => set({ excludeText: t }),
        setFromDate: (d) => set({ fromDate: d }),
        setFromTime: (t) => set({ fromTime: t }),
        setToDate: (d) => set({ toDate: d }),
        setToTime: (t) => set({ toTime: t }),
        setActiveQuick: (q) => set({ activeQuick: q }),
        setAllLines: (l) => set({ allLines: l }),
        setTotalCount: (c) => set({ totalCount: c }),
        setVolumeData: (v) => set({ volumeData: v }),
        setIssueDesc: (d) => set({ issueDesc: d }),
        setAnalysisResult: (r) => set({ analysisResult: r }),
        setProviders: (p) => set({ providers: p }),
        setActiveProvider: (p) => set({ activeProvider: p }),
        resetInvestigate: () => set(initialState),
      }),
      {
        name: "amr-investigate-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
        partialize: (state) => ({
          env: state.env,
          selectedSite: state.selectedSite,
          siteOptions: state.siteOptions,
          hostnameOptions: state.hostnameOptions,
          selectedHostnames: state.selectedHostnames,
          deploymentOptions: state.deploymentOptions,
          selectedDeployments: state.selectedDeployments,
          searchText: state.searchText,
          excludeText: state.excludeText,
          fromDate: state.fromDate,
          fromTime: state.fromTime,
          toDate: state.toDate,
          toTime: state.toTime,
          activeQuick: state.activeQuick,
          issueDesc: state.issueDesc,
          providers: state.providers,
          activeProvider: state.activeProvider,
        }),
      }
    ),
    { name: "InvestigateStore", enabled: process.env.NODE_ENV === "development" }
  )
);
