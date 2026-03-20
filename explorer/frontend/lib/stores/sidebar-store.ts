import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SidebarState {
  pinned: boolean;
  togglePin: () => void;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      pinned: false,
      togglePin: () => set((s) => ({ pinned: !s.pinned })),
    }),
    {
      name: "sidebar-pinned",
    }
  )
);
