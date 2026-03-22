import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type {
  SiteMapMeta,
  SiteMapData,
  SiteMapMarker,
  TrajectoryPoint,
} from "@/lib/types";
import type { Layers } from "@/components/sitemap/SiteMapCanvas";

interface SitemapState {
  // Persisted (lightweight)
  siteId: string;
  searchQuery: string;
  layers: Layers;
  hiddenSpotTypes: string[];
  hiddenRegionTypes: string[];
  trajectoryBag: string;

  // In-memory only (heavy — excluded from sessionStorage via partialize)
  meta: SiteMapMeta | null;
  mapData: SiteMapData | null;
  markers: SiteMapMarker[];
  trajectory: TrajectoryPoint[];
  /** True bag start/end (Unix seconds) — may differ from first/last pose timestamp. */
  bagTimeRange: { start: number; end: number } | null;

  setSiteId: (id: string) => void;
  setMeta: (m: SiteMapMeta | null) => void;
  setMapData: (d: SiteMapData | null) => void;
  setMarkers: (m: SiteMapMarker[]) => void;
  setTrajectory: (t: TrajectoryPoint[]) => void;
  setTrajectoryBag: (b: string) => void;
  setBagTimeRange: (r: { start: number; end: number } | null) => void;
  setSearchQuery: (q: string) => void;
  setLayers: (l: Layers) => void;
  setHiddenSpotTypes: (t: string[]) => void;
  setHiddenRegionTypes: (t: string[]) => void;
  resetSitemap: () => void;
}

const initialState = {
  siteId: "",
  meta: null as SiteMapMeta | null,
  mapData: null as SiteMapData | null,
  markers: [] as SiteMapMarker[],
  trajectory: [] as TrajectoryPoint[],
  bagTimeRange: null as { start: number; end: number } | null,
  trajectoryBag: "",
  searchQuery: "",
  layers: {
    spots: true,
    racks: true,
    regions: true,
    markers: true,
    nodes: true,
  } as Layers,
  hiddenSpotTypes: [] as string[],
  hiddenRegionTypes: [] as string[],
};

export const useSitemapStore = create<SitemapState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setSiteId: (id) => set({ siteId: id }),
        setMeta: (m) => set({ meta: m }),
        setMapData: (d) => set({ mapData: d }),
        setMarkers: (m) => set({ markers: m }),
        setTrajectory: (t) => set({ trajectory: t }),
        setTrajectoryBag: (b) => set({ trajectoryBag: b }),
        setBagTimeRange: (r) => set({ bagTimeRange: r }),
        setSearchQuery: (q) => set({ searchQuery: q }),
        setLayers: (l) => set({ layers: l }),
        setHiddenSpotTypes: (t) => set({ hiddenSpotTypes: t }),
        setHiddenRegionTypes: (t) => set({ hiddenRegionTypes: t }),
        resetSitemap: () => set(initialState),
      }),
      {
        name: "amr-sitemap-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
        partialize: (state) => ({
          siteId: state.siteId,
          searchQuery: state.searchQuery,
          layers: state.layers,
          hiddenSpotTypes: state.hiddenSpotTypes,
          hiddenRegionTypes: state.hiddenRegionTypes,
          trajectoryBag: state.trajectoryBag,
        }),
      }
    ),
    { name: "SitemapStore", enabled: process.env.NODE_ENV === "development" }
  )
);
