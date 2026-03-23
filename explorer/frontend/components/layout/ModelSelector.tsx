"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Check, Cpu, Sparkles, BrainCircuit, X, Loader2 } from "lucide-react";
import clsx from "clsx";
import type { AIProviderInfo } from "@/lib/types";

interface ModelSelectorProps {
  providers: AIProviderInfo[];
  /** Currently selected model id (effective model for this scope). null = no selection. */
  value: string | null;
  /** Called when user picks a new model — caller is responsible for backend switch. */
  onChange: (id: string) => Promise<void> | void;
  /** If true, show the amber tint indicating this is a page-level override. */
  isOverride?: boolean;
  /** Called when the user clicks the "Clear override" button inside the dropdown. */
  onClearOverride?: () => void;
  /** Whether providers are still loading. */
  loading?: boolean;
  /** Disable the selector entirely. */
  disabled?: boolean;
  /** Fallback label shown when no model is selected. Defaults to "Model". */
  label?: string;
  /** Visual size. "sm" = compact (h-7), "md" = slightly taller (h-8). Defaults to "sm". */
  size?: "sm" | "md";
}

/** Icon per provider type */
function ProviderIcon({
  type,
  size: sz = 11,
  className = "",
}: {
  type: string;
  size?: number;
  className?: string;
}) {
  if (type === "openai") return <Sparkles size={sz} className={className} />;
  if (type === "gemini") return <BrainCircuit size={sz} className={className} />;
  return <Cpu size={sz} className={className} />;
}

/** Dim group label inside the dropdown panel */
function GroupLabel({ label }: { label: string }) {
  return (
    <p className="px-3 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-widest text-slate-600 select-none">
      {label}
    </p>
  );
}

/** Single option row inside the dropdown panel */
function ModelOption({
  provider,
  selected,
  onSelect,
}: {
  provider: AIProviderInfo;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onMouseDown={() => onSelect(provider.id)}
      className={clsx(
        "w-full flex items-center gap-2 px-3 py-1.5 text-xs transition-colors hover:bg-white/[0.05]",
        selected ? "text-blue-300" : "text-slate-300"
      )}
    >
      <span className="w-3 shrink-0">
        {selected && <Check size={11} className="text-blue-400" />}
      </span>
      <ProviderIcon
        type={provider.type}
        size={11}
        className={selected ? "text-blue-400" : "text-slate-500"}
      />
      <span className="truncate">{provider.name}</span>
    </button>
  );
}

/**
 * Shared AI model selector used across all pages.
 *
 * Renders as a compact pill button — matching the site/branch selector design —
 * that opens a custom grouped dropdown with Ollama / OpenAI / Gemini sections.
 * Override state is indicated with an amber tint + dot, with a clear action in
 * the dropdown footer.
 */
export default function ModelSelector({
  providers,
  value,
  onChange,
  isOverride,
  onClearOverride,
  loading,
  disabled,
  label = "Model",
  size = "sm",
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handle(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [open]);

  // Auto-clear switch errors after 3 s
  useEffect(() => {
    if (!switchError) return;
    const t = setTimeout(() => setSwitchError(""), 3000);
    return () => clearTimeout(t);
  }, [switchError]);

  const ollama = providers.filter((p) => p.type === "ollama");
  const openai = providers.filter((p) => p.type === "openai");
  const gemini = providers.filter((p) => p.type === "gemini");

  const activeProvider = providers.find((p) => p.id === value);
  const displayName = switching
    ? "Switching…"
    : loading && providers.length === 0
      ? "Loading…"
      : activeProvider?.name ?? (providers.length === 0 ? "No models" : label);

  async function pick(id: string) {
    if (id === value) { setOpen(false); return; }
    setOpen(false);
    setSwitching(true);
    setSwitchError("");
    try {
      await onChange(id);
    } catch {
      setSwitchError("Switch failed");
    } finally {
      setSwitching(false);
    }
  }

  const isDisabled = disabled || switching || (providers.length === 0 && !loading);

  return (
    <div className="relative inline-flex items-center gap-1.5 shrink-0" ref={containerRef}>

      {/* ── Trigger pill ─────────────────────────────────────────────────── */}
      <div
        className={clsx(
          "flex items-center gap-1.5 rounded-lg border text-xs font-medium transition-all select-none",
          size === "sm" ? "h-7 pl-2.5 pr-2" : "h-8 pl-3 pr-2.5",
          isDisabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer",
          isOverride
            ? open
              ? "bg-amber-400/15 border-amber-400/50 text-amber-300"
              : "bg-amber-400/10 border-amber-400/25 text-amber-300 hover:bg-amber-400/15 hover:border-amber-400/40"
            : open
              ? "bg-blue-500/15 border-blue-500/40 text-blue-300"
              : "bg-white/[0.05] border-white/[0.08] text-slate-300 hover:bg-white/[0.08] hover:border-white/[0.14] hover:text-slate-100"
        )}
        onClick={() => { if (!isDisabled) setOpen((v) => !v); }}
        title={isOverride ? `Page override: ${activeProvider?.name ?? value ?? ""}` : activeProvider?.name}
      >
        {/* Left icon */}
        {switching
          ? <Loader2 size={11} className="animate-spin text-sky-400" />
          : <ProviderIcon
              type={activeProvider?.type ?? "ollama"}
              size={11}
              className={isOverride ? "text-amber-400" : open ? "text-blue-400" : "text-slate-500"}
            />
        }

        {/* Model name */}
        <span className="max-w-[120px] truncate">{displayName}</span>

        {/* Override dot indicator */}
        {isOverride && (
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
        )}

        {/* Chevron */}
        <ChevronDown
          size={10}
          className={clsx("transition-transform shrink-0", open && "rotate-180")}
        />
      </div>

      {/* ── Error toast ───────────────────────────────────────────────────── */}
      {switchError && (
        <span className="text-[10px] text-red-400 shrink-0">{switchError}</span>
      )}

      {/* ── Dropdown panel ───────────────────────────────────────────────── */}
      {open && (
        <div className="absolute top-full mt-1.5 left-0 z-[70] w-52 bg-[#0f172a] border border-white/[0.1] rounded-xl shadow-2xl shadow-black/60 flex flex-col overflow-hidden">

          {/* Panel header */}
          <div className="flex items-center gap-1.5 px-3 py-2 border-b border-white/[0.06]">
            <Cpu size={11} className="text-slate-500" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
              AI Model
            </span>
            {isOverride && (
              <span className="ml-auto text-[9px] font-medium text-amber-400 bg-amber-400/10 rounded px-1 py-0.5">
                page override
              </span>
            )}
          </div>

          {/* Options */}
          <div className="max-h-64 overflow-y-auto overscroll-contain py-1">
            {providers.length === 0 && (
              <p className="px-3 py-2 text-xs text-slate-500">
                {loading ? "Loading models…" : "No models available"}
              </p>
            )}

            {ollama.length > 0 && (
              <>
                <GroupLabel label="Local (Ollama)" />
                {ollama.map((p) => (
                  <ModelOption key={p.id} provider={p} selected={p.id === value} onSelect={pick} />
                ))}
              </>
            )}

            {openai.length > 0 && (
              <>
                <GroupLabel label="OpenAI" />
                {openai.map((p) => (
                  <ModelOption key={p.id} provider={p} selected={p.id === value} onSelect={pick} />
                ))}
              </>
            )}

            {gemini.length > 0 && (
              <>
                <GroupLabel label="Google Gemini" />
                {gemini.map((p) => (
                  <ModelOption key={p.id} provider={p} selected={p.id === value} onSelect={pick} />
                ))}
              </>
            )}
          </div>

          {/* Clear override footer */}
          {isOverride && onClearOverride && (
            <div className="border-t border-white/[0.06]">
              <button
                type="button"
                onMouseDown={onClearOverride}
                className="w-full flex items-center gap-2 px-3 py-2 text-[10px] text-amber-400/70 hover:text-amber-300 hover:bg-amber-400/5 transition-colors"
              >
                <X size={10} />
                Clear override (use global)
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
