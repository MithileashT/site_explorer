"use client";

import { useState, useEffect } from "react";
import { getRIOStatus, fetchBagFromRIO } from "@/lib/api";
import type { RIOStatusResponse } from "@/lib/types";
import {
  CloudDownload,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Info,
  Link,
  HardDrive,
} from "lucide-react";

interface Props {
  onFetched: (bagPath: string) => void;
}

type FetchStatus = "idle" | "fetching" | "done" | "error";
type FetchMode = "url" | "device";

export default function RIOFetchPanel({ onFetched }: Props) {
  const [rioStatus, setRioStatus] = useState<RIOStatusResponse | null>(null);
  const [mode, setMode] = useState<FetchMode>("url");
  const [url, setUrl] = useState("");
  const [device, setDevice] = useState("");
  const [filename, setFilename] = useState("");
  const [projectOverride, setProjectOverride] = useState("");
  const [status, setStatus] = useState<FetchStatus>("idle");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    getRIOStatus()
      .then(setRioStatus)
      .catch(() => setRioStatus(null));
  }, []);

  const configured = rioStatus?.configured ?? false;
  const cliAvailable = rioStatus?.rio_cli_available ?? false;

  const canSubmit =
    status !== "fetching" &&
    configured &&
    (mode === "url"
      ? url.trim().length > 0
      : device.trim().length > 0 && filename.trim().length > 0) &&
    (mode === "url" || cliAvailable);

  async function handleFetch() {
    if (!canSubmit) return;
    setStatus("fetching");
    setMsg("Downloading from RIO… (this may take a few minutes for large bags)");
    try {
      const params =
        mode === "url"
          ? {
              shared_url: url.trim(),
              ...(projectOverride.trim() && { project_override: projectOverride.trim() }),
            }
          : {
              device: device.trim(),
              filename: filename.trim(),
              ...(projectOverride.trim() && { project_override: projectOverride.trim() }),
            };
      const res = await fetchBagFromRIO(params);
      setMsg(`Downloaded ${res.filename} (${res.size_mb.toFixed(1)} MB)`);
      setStatus("done");
      onFetched(res.bag_path);
    } catch (e: unknown) {
      const errMsg = e instanceof Error ? e.message : "RIO fetch failed";
      setMsg(errMsg);
      setStatus("error");
    }
  }

  return (
    <div className="space-y-3">
      {/* ── Config status badges ─────────────────────────── */}
      {rioStatus !== null && (
        <div className="space-y-1.5">
          {!configured && (
            <div className="flex items-center gap-2 text-xs rounded px-2.5 py-1.5 bg-amber-900/20 text-amber-400 border border-amber-800/30">
              <AlertTriangle size={12} />
              RIO is not configured on this server. Run{" "}
              <code className="mx-1 bg-slate-800 px-1 rounded">rio auth login</code> on the host.
            </div>
          )}
          {configured && !cliAvailable && (
            <div className="flex items-center gap-2 text-xs rounded px-2.5 py-1.5 bg-blue-900/20 text-blue-400 border border-blue-800/30">
              <Info size={12} />
              rio CLI not found — device upload unavailable. Shared URL fetch still works.
            </div>
          )}
          {configured && !rioStatus.has_project && (
            <div className="flex items-center gap-2 text-xs rounded px-2.5 py-1.5 bg-amber-900/20 text-amber-400 border border-amber-800/30">
              <AlertTriangle size={12} />
              No project selected. Run{" "}
              <code className="mx-1 bg-slate-800 px-1 rounded">rio project select &lt;project&gt;</code>{" "}
              on the host.
            </div>
          )}
          {configured && (
            <div className="flex items-center gap-2 text-xs rounded px-2.5 py-1.5 bg-emerald-900/20 text-emerald-400 border border-emerald-800/30">
              <CheckCircle size={12} />
              RIO configured — org:{" "}
              <span className="font-mono">{rioStatus.organization || "—"}</span>, project:{" "}
              <span className="font-mono">{rioStatus.project || "—"}</span>
            </div>
          )}
        </div>
      )}

      {/* ── Mode toggle ──────────────────────────────────── */}
      <div className="flex gap-2">
        {(
          [
            { id: "url" as FetchMode, label: "Shared URL", icon: Link },
            { id: "device" as FetchMode, label: "Device Upload", icon: HardDrive },
          ] as const
        ).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setMode(id)}
            disabled={id === "device" && !cliAvailable}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
              mode === id
                ? "bg-blue-600/20 text-blue-400 border border-blue-600/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent"
            } ${id === "device" && !cliAvailable ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* ── Shared URL input ─────────────────────────────── */}
      {mode === "url" && (
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://gaapiserver.apps.rapyuta.io/sharedurl/…"
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
          disabled={status === "fetching"}
        />
      )}

      {/* ── Device + Filename inputs ─────────────────────── */}
      {mode === "device" && (
        <div className="grid grid-cols-2 gap-2">
          <input
            value={device}
            onChange={(e) => setDevice(e.target.value)}
            placeholder="Device Name (e.g. oksbot24)"
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
            disabled={status === "fetching"}
          />
          <input
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="File Name (e.g. robot24_20260318.bag)"
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
            disabled={status === "fetching"}
          />
        </div>
      )}

      {/* ── Project override ─────────────────────────────── */}
      <input
        value={projectOverride}
        onChange={(e) => setProjectOverride(e.target.value)}
        placeholder="Project Override (optional)"
        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
        disabled={status === "fetching"}
      />

      {/* ── Fetch button ─────────────────────────────────── */}
      <button
        onClick={handleFetch}
        disabled={!canSubmit}
        className="btn btn-primary w-full py-2.5 text-sm gap-2 disabled:opacity-40"
      >
        {status === "fetching" ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <CloudDownload size={14} />
        )}
        Fetch Bag
      </button>

      {/* ── Status message ───────────────────────────────── */}
      {msg && (
        <div
          className={`flex items-center gap-2 text-sm ${
            status === "done"
              ? "text-emerald-400"
              : status === "error"
              ? "text-red-400"
              : "text-slate-400"
          }`}
        >
          {status === "done" && <CheckCircle size={14} />}
          {status === "error" && <XCircle size={14} />}
          {status === "fetching" && <Loader2 size={14} className="animate-spin" />}
          {msg}
        </div>
      )}
    </div>
  );
}
