"use client";

import { useEffect, useState } from "react";
import { analyzeBag, fetchTimeline } from "@/lib/api";
import { useBagsStore } from "@/lib/stores/bags-store";
import { useHydrated } from "@/lib/stores/use-hydrated";
import BagUpload from "@/components/bags/BagUpload";
import RIOFetchPanel from "@/components/bags/RIOFetchPanel";
import RIOUploadPanel from "@/components/bags/RIOUploadPanel";
import LogVolumeChart from "@/components/bags/LogVolumeChart";
import BagLogDebugger from "@/components/bags/BagLogDebugger";
import MapDiffPanel from "@/components/bags/MapDiffPanel";
import ReactMarkdown from "react-markdown";
import {
  PackageSearch,
  Loader2,
  GitCompare,
  ChevronDown,
  ChevronRight,
  Info,
  Bot,
  UploadCloud,
  CloudDownload,
  Radio,
} from "lucide-react";

type Tab = "logs" | "mapdiff";
type BagSource = "upload" | "rio" | "device";

export default function BagsPage() {
  // Persisted state from store
  const { bagPath, setBagPath, timeline, setTimeline, analysis, setAnalysis, tab, setTab, bagSource, setBagSource, resetBags } = useBagsStore();
  const hydrated = useHydrated();
  // Transient local state — NOT persisted
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [showRawLLM, setShowRawLLM] = useState(false);

  // Re-fetch timeline on reload if bagPath is persisted but timeline was lost
  useEffect(() => {
    if (bagPath && !timeline) {
      fetchTimeline(bagPath).then(setTimeline).catch(() => {});
    }
  }, [bagPath, timeline, setTimeline]);

  async function onUploaded(path: string) {
    resetBags();
    setBagPath(path);
    setError("");
    try {
      const tl = await fetchTimeline(path);
      setTimeline(tl);
    } catch {
      /* timeline is optional */
    }
  }

  async function runAnalysis(windowStart?: number, windowEnd?: number) {
    if (!bagPath) return;
    setAnalyzing(true);
    setError("");
    try {
      const res = await analyzeBag(bagPath, windowStart, windowEnd);
      setAnalysis(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  function onRangeSelect(start: number, end: number) {
    runAnalysis(start, end);
  }

  return (
    <div className="p-6 max-w-6xl mx-auto animate-fade-in space-y-5" style={{ visibility: hydrated ? "visible" : "hidden" }}>
      {/* ── Header ────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <PackageSearch size={20} className="text-blue-400" />
        <div>
          <h1 className="text-xl font-bold text-slate-100">Bag Analyzer</h1>
          <p className="text-xs text-slate-400">
            Upload a ROS bag, explore logs with timeline, run AI analysis
          </p>
        </div>
      </div>

      {/* ── Bag Source (Upload / RIO) ─────────────────────── */}
      <section className="card">
        <div className="flex gap-2 mb-3">
          {(
            [
              { id: "upload", label: "Upload File", icon: UploadCloud },
              { id: "rio", label: "Fetch from RIO", icon: CloudDownload },
              { id: "device", label: "Device Upload", icon: Radio },
            ] as { id: BagSource; label: string; icon: React.ElementType }[]
          ).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setBagSource(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
                bagSource === id
                  ? "bg-blue-600/20 text-blue-400 border border-blue-600/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent"
              }`}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>
        {bagSource === "upload" && <BagUpload onUploaded={onUploaded} />}
        {bagSource === "rio" && <RIOFetchPanel onFetched={onUploaded} />}
        {bagSource === "device" && <RIOUploadPanel onUploaded={() => setError("")} />}
      </section>

      {/* ── Collapsible Timeline ──────────────────────────── */}
      {timeline && (
        <section className="card p-0 overflow-hidden">
          <button
            onClick={() => setTimelineOpen((p) => !p)}
            className="flex items-center gap-2 w-full px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider hover:bg-white/5 transition-colors"
          >
            {timelineOpen ? (
              <ChevronDown size={14} />
            ) : (
              <ChevronRight size={14} />
            )}
            Log Volume Timeline
          </button>
          {timelineOpen && (
            <div className="px-4 pb-4">
              <LogVolumeChart
                buckets={timeline.buckets}
                onRangeSelect={onRangeSelect}
              />
              <p className="text-xs text-slate-500 mt-2">
                Drag on the timeline to select a time range and analyze logs
              </p>
            </div>
          )}
        </section>
      )}

      {/* ── Analyze button ────────────────────────────────── */}
      {bagPath && !analyzing && (
        <button
          className="btn btn-primary w-full py-3 text-sm gap-2"
          onClick={() => runAnalysis()}
        >
          <PackageSearch size={16} />
          Analyze Full Bag
        </button>
      )}

      {/* ── Loading ───────────────────────────────────────── */}
      {analyzing && (
        <div className="flex items-center justify-center gap-3 text-blue-300 py-10">
          <Loader2 className="animate-spin" size={22} />
          <span className="text-sm">Running analysis… this may take a moment</span>
        </div>
      )}

      {/* ── Error ─────────────────────────────────────────── */}
      {error && (
        <div className="card border-red-800/30 bg-red-900/10 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* ── Analysis Results ──────────────────────────────── */}
      {analysis && (
        <>
          {/* Stats bar — 4 cards, no Critical / Anomalies */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {(
              [
                { label: "Duration", value: `${analysis.duration_secs.toFixed(1)}s` },
                { label: "Messages", value: analysis.total_messages },
                { label: "Errors", value: analysis.error_count, cls: "text-red-400" },
                { label: "Warnings", value: analysis.warning_count, cls: "text-amber-400" },
              ] as { label: string; value: string | number; cls?: string }[]
            ).map(({ label, value, cls }) => (
              <div key={label} className="card text-center py-3">
                <p className={`text-xl font-bold ${cls ?? "text-slate-100"}`}>
                  {value}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">{label}</p>
              </div>
            ))}
          </div>

          {/* Engine hypothesis */}
          {analysis.engine_hypothesis && (
            <div className="card border-l-2 border-blue-500 rounded-l-none bg-blue-900/10">
              <div className="flex items-center gap-1.5 mb-1 text-xs font-semibold text-blue-300 uppercase tracking-wide">
                <Info size={13} /> Rule-Engine Hypothesis
              </div>
              <p className="text-xs text-slate-400">
                {analysis.engine_hypothesis}
              </p>
            </div>
          )}

          {/* Tab bar */}
          <div className="flex gap-2 border-b border-slate-700/50 pb-2">
            {(
              [
                { id: "logs", label: "Log Analysis", icon: PackageSearch },
                { id: "mapdiff", label: "Map Diff", icon: GitCompare },
              ] as { id: Tab; label: string; icon: React.ElementType }[]
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-colors ${
                  tab === id
                    ? "bg-blue-600/20 text-blue-400 border border-blue-600/30"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
                }`}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {tab === "logs" && <BagLogDebugger analysis={analysis} />}
          {tab === "mapdiff" && bagPath && (
            <div className="card">
              <MapDiffPanel bagPath={bagPath} />
            </div>
          )}

          {/* ── LLM Analysis (bottom) ─────────────────────── */}
          <section className="card">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                <Bot size={13} className="text-blue-400" /> AI Analysis
              </h3>
              <div className="flex items-center gap-2">
                {(analysis.actual_total_tokens ?? 0) > 0 && (() => {
                  const pin  = analysis.actual_prompt_tokens     ?? 0;
                  const pout = analysis.actual_completion_tokens ?? 0;
                  const cost = analysis.cost_usd ?? (pin * 2.00 + pout * 8.00) / 1_000_000;
                  return (
                    <span
                      className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400"
                      title={`Actual tokens · in=${pin.toLocaleString()} out=${pout.toLocaleString()} · gpt-4.1: $2/M in, $8/M out`}
                    >
                      {pin.toLocaleString()} in | {pout.toLocaleString()} out
                      {" · "}<span className="text-emerald-400">${cost.toFixed(4)}</span>
                    </span>
                  );
                })()}
                {analysis.llm_summary && (
                  <button
                    onClick={() => setShowRawLLM((p) => !p)}
                    className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                  >
                    {showRawLLM ? "Formatted" : "Raw"}
                  </button>
                )}
              </div>
            </div>
            {analysis.llm_summary ? (
              showRawLLM ? (
                <pre className="text-xs text-slate-400 whitespace-pre-wrap font-mono overflow-x-auto">
                  {analysis.llm_summary}
                </pre>
              ) : (
                <div className="prose-dark">
                  <ReactMarkdown>{analysis.llm_summary}</ReactMarkdown>
                </div>
              )
            ) : (
              <p className="text-xs text-slate-500">
                AI analysis will appear here after running analysis.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
