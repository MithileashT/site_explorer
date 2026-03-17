"use client";

import { useEffect, useState, useCallback } from "react";
import { ChevronDown, ChevronUp, RotateCcw, DollarSign } from "lucide-react";
import { fetchAIUsage, resetAIUsage } from "@/lib/api";
import type { AIUsageResponse, ModuleUsage } from "@/lib/types";

const MODULE_LABELS: Record<string, string> = {
  log_analyser: "Log Analyzer",
  bag_analyser: "Bag Analyzer",
  slack_investigation: "Slack Investigation",
  other: "Other",
};

function fmt$(v: number) {
  return v < 0.01 ? `$${v.toFixed(6)}` : `$${v.toFixed(4)}`;
}

function fmtK(v: number) {
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v);
}

function ModuleRow({ name, usage }: { name: string; usage: ModuleUsage }) {
  return (
    <div className="flex items-center justify-between text-[11px] py-1">
      <span className="text-slate-400 truncate max-w-[100px]">{MODULE_LABELS[name] ?? name}</span>
      <div className="flex items-center gap-2 text-slate-300">
        <span title="Requests">{usage.request_count}×</span>
        <span title="Total tokens">{fmtK(usage.total_tokens)}</span>
        <span className="text-emerald-400 font-medium" title="Cost">{fmt$(usage.cost_usd)}</span>
      </div>
    </div>
  );
}

export default function CostDashboard() {
  const [data, setData] = useState<AIUsageResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await fetchAIUsage();
      setData(d);
      setErr(false);
    } catch {
      setErr(true);
    }
  }, []);

  // Only fetch when panel is opened; poll every 15s while open
  useEffect(() => {
    if (!open) return;
    load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, [open, load]);

  const handleReset = async () => {
    try {
      await resetAIUsage();
      load();
    } catch { /* ignore */ }
  };

  const totalCost = data?.totals.cost_usd ?? 0;
  const totalReqs = data?.totals.request_count ?? 0;

  return (
    <div className="border-t border-[#1f2937]">
      {/* Collapsed summary — always visible */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-[11px] hover:bg-white/5 transition-colors"
      >
        <span className="flex items-center gap-1.5 text-slate-400">
          <DollarSign size={12} className="text-emerald-400" />
          Session Cost
        </span>
        <span className="flex items-center gap-1.5">
          <span className="text-emerald-400 font-medium">
            {err ? "—" : fmt$(totalCost)}
          </span>
          {open ? <ChevronDown size={12} className="text-slate-500" /> : <ChevronUp size={12} className="text-slate-500" />}
        </span>
      </button>

      {/* Expanded detail */}
      {open && data && (
        <div className="px-3 pb-3 space-y-2">
          {/* Totals bar */}
          <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-2.5 py-2">
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-emerald-300 font-medium">Total</span>
              <span className="text-emerald-400 font-semibold">{fmt$(totalCost)}</span>
            </div>
            <div className="flex items-center justify-between text-[10px] text-slate-400 mt-0.5">
              <span>{totalReqs} request{totalReqs !== 1 ? "s" : ""}</span>
              <span>{fmtK(data.totals.total_tokens)} tokens</span>
            </div>
          </div>

          {/* Per-module breakdown */}
          {Object.keys(data.modules).length > 0 && (
            <div className="space-y-0.5">
              <span className="text-[10px] font-medium uppercase tracking-wider text-slate-500">By Module</span>
              {Object.entries(data.modules).map(([mod, usage]) => (
                <ModuleRow key={mod} name={mod} usage={usage} />
              ))}
            </div>
          )}

          {/* Model + uptime + reset */}
          <div className="flex items-center justify-between pt-1 text-[10px] text-slate-500">
            <span className="truncate max-w-[120px]" title={`${data.active_provider}:${data.active_model}`}>
              {data.active_model}
            </span>
            <span>{Math.floor(data.uptime_seconds / 60)}m uptime</span>
          </div>

          <button
            onClick={handleReset}
            className="w-full flex items-center justify-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 py-1 rounded hover:bg-white/5 transition-colors"
          >
            <RotateCcw size={10} /> Reset Session
          </button>
        </div>
      )}
    </div>
  );
}
