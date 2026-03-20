"use client";

import { useRef, useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  PackageSearch,
  SearchCode,
  Bot,
  Activity,
  Warehouse,
  MessagesSquare,
  DollarSign,
} from "lucide-react";
import clsx from "clsx";
import CostDashboard from "@/components/dashboard/CostDashboard";

const NAV = [
  { href: "/",            label: "Dashboard",           icon: LayoutDashboard  },
  { href: "/sitemap",     label: "Site Map",            icon: Warehouse        },
  { href: "/bags",        label: "Bag Analyzer",        icon: PackageSearch    },
  { href: "/investigate", label: "Log Analyzer",        icon: SearchCode       },
  { href: "/slack-investigation", label: "Slack Investigation", icon: MessagesSquare },
  { href: "/assistant",   label: "AI Assistant",        icon: Bot              },
];

export default function Sidebar() {
  const path = usePathname();
  const [costOpen, setCostOpen] = useState(false);
  const costRef = useRef<HTMLDivElement>(null);

  // Close cost popover on outside click
  useEffect(() => {
    if (!costOpen) return;
    function handleClick(e: MouseEvent) {
      if (costRef.current && !costRef.current.contains(e.target as Node)) {
        setCostOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [costOpen]);

  return (
    <aside className="sidebar-rail flex flex-col min-h-screen bg-[#111827] border-r border-[#1f2937] shrink-0 overflow-visible relative">
      {/* Logo */}
      <div className="nav-item flex items-center justify-center py-4 border-b border-[#1f2937] min-h-[57px]">
        <Activity className="text-blue-400 shrink-0" size={20} />
        <span className="nav-tooltip">AMR Platform</span>
      </div>

      {/* Navigation */}
      <nav className="flex flex-col gap-0.5 flex-1 p-2 pt-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = path === href || (href !== "/" && path.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "nav-item relative flex items-center justify-center rounded-lg py-2 transition-colors",
                active
                  ? "bg-blue-600/20 text-blue-400 border border-blue-600/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
              )}
            >
              <Icon
                size={18}
                className={clsx("shrink-0", active ? "text-blue-400" : "text-slate-500")}
              />
              <span className="nav-tooltip">{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom actions */}
      <div className="border-t border-[#1f2937] flex flex-col">
        {/* Cost button */}
        <div ref={costRef} className="relative">
          <button
            onClick={() => setCostOpen((o) => !o)}
            className="nav-item w-full flex items-center justify-center py-2.5 hover:bg-white/5 transition-colors text-slate-400"
          >
            <DollarSign size={14} className="text-emerald-400 shrink-0" />
            <span className="nav-tooltip">Session Cost</span>
          </button>
          {costOpen && (
            <div className="cost-popover">
              <div className="card">
                <CostDashboard />
              </div>
            </div>
          )}
        </div>

        {/* Footer version */}
        <div className="px-4 py-2 border-t border-[#1f2937] text-[10px] text-slate-600 text-center">
          v0.1
        </div>
      </div>
    </aside>
  );
}
