"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import clsx from "clsx";
import { getRIOStatus, getRIOProjects, getRIODevices, triggerRIOUpload, subscribeUploadStatus, discoverRIOBags } from "@/lib/api";
import type { RIOStatusResponse, RIOProject, RIOUploadEvent } from "@/lib/types";
import TimezoneSelector from "./TimezoneSelector";
import {
  localDatetimeToEpoch,
  epochToLocalDatetime,
  formatUtcPreview,
  getSystemTimezone,
  getTimezoneShortLabel,
  getTimezoneOffsetMinutes,
} from "@/lib/timezone-utils";
import {
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Upload,
  ExternalLink,
  Server,
  MonitorSmartphone,
  Search,
  Archive,
  ArrowUpCircle,
  ChevronDown,
  Check,
} from "lucide-react";

interface Props {
  onUploaded?: (msg: string) => void;
}

type UploadStatus = "idle" | "uploading" | "done" | "error";

/** Per-device progress state shown in the UI. */
interface DeviceProgress {
  phase: "pending" | "discovering" | "compressing" | "uploading" | "done" | "error";
  message: string;
  url?: string;
  filename?: string;
  request_uuid?: string;
}

export default function RIOUploadPanel({ onUploaded }: Props) {
  const [rioStatus, setRioStatus] = useState<RIOStatusResponse | null>(null);
  const [projects, setProjects] = useState<RIOProject[]>([]);
  const [selectedProject, setSelectedProject] = useState<RIOProject | null>(null);
  const [devices, setDevices] = useState<string[]>([]);
  const [selectedDevices, setSelectedDevices] = useState<string[]>([]);
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [msg, setMsg] = useState("");
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [uploadSpeedMbps, setUploadSpeedMbps] = useState(10);

  // Project combobox dropdown
  const [showProjectDropdown, setShowProjectDropdown] = useState(false);
  const [projectQuery, setProjectQuery] = useState("");
  const projectDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showProjectDropdown) return;
    function handleOutside(e: MouseEvent) {
      if (projectDropdownRef.current && !projectDropdownRef.current.contains(e.target as Node)) {
        setShowProjectDropdown(false);
        setProjectQuery("");
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [showProjectDropdown]);

  const filteredProjects = useMemo(() => {
    const q = projectQuery.toLowerCase().trim();
    if (!q) return projects;
    return projects.filter(p =>
      p.name.toLowerCase().includes(q) || p.guid.toLowerCase().includes(q)
    );
  }, [projects, projectQuery]);

  // Group filtered projects by org_name for dropdown section headers.
  // Groups are sorted so the one with the alphabetically-first project name
  // appears first, keeping the overall dropdown as close to A-Z as possible.
  const groupedProjects = useMemo(() => {
    const map = new Map<string, RIOProject[]>();
    for (const p of filteredProjects) {
      const key = p.org_name || "";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(p);
    }
    return Array.from(map.entries()).sort((a, b) =>
      (a[1][0]?.name ?? "").localeCompare(b[1][0]?.name ?? "")
    );
  }, [filteredProjects]);

  const showGroups = groupedProjects.length > 1;

  // Timezone
  const systemTz = getSystemTimezone();
  const [selectedTz, setSelectedTz] = useState(systemTz);

  // Discover preview
  const [previewBags, setPreviewBags] = useState<string[] | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");

  // Per-device progress map
  const [deviceProgress, setDeviceProgress] = useState<Record<string, DeviceProgress>>({});

  // Keep EventSource ref so we can close on unmount
  const esRef = useRef<EventSource | null>(null);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => { esRef.current?.close(); };
  }, []);

  // Load RIO status + projects on mount
  useEffect(() => {
    getRIOStatus()
      .then(setRioStatus)
      .catch(() => setRioStatus(null));

    setLoadingProjects(true);
    getRIOProjects()
      .then((res) => {
        setProjects(res.projects);
        if (res.projects.length > 0) {
          // Auto-select the alphabetically first project across all orgs
          const first = [...res.projects].sort((a, b) =>
            a.name.toLowerCase().localeCompare(b.name.toLowerCase())
          )[0];
          setSelectedProject(first);
        }
      })
      .catch(() => setProjects([]))
      .finally(() => setLoadingProjects(false));
  }, []);

  // Fetch devices whenever selected project changes
  useEffect(() => {
    if (!selectedProject) return;
    setDevices([]);
    setSelectedDevices([]);
    setLoadingDevices(true);
    getRIODevices({ project_guid: selectedProject.guid })
      .then((res) => setDevices(res.devices))
      .catch(() => setDevices([]))
      .finally(() => setLoadingDevices(false));
  }, [selectedProject]);

  // Set default time range (last 10 minutes in selected timezone)
  useEffect(() => {
    const nowEpoch = Math.floor(Date.now() / 1000);
    const tenMinAgoEpoch = nowEpoch - 600;
    setEndTime(epochToLocalDatetime(nowEpoch, selectedTz));
    setStartTime(epochToLocalDatetime(tenMinAgoEpoch, selectedTz));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTz]);



  function toggleDevice(name: string) {
    setSelectedDevices((prev) =>
      prev.includes(name) ? prev.filter((d) => d !== name) : [...prev, name]
    );
  }

  function selectAllDevices() {
    setSelectedDevices(
      selectedDevices.length === devices.length ? [] : [...devices]
    );
  }

  const canSubmit =
    status !== "uploading" &&
    selectedProject !== null &&
    selectedDevices.length > 0 &&
    startTime &&
    endTime;

  /** Handle SSE events to update per-device progress. */
  const handleSSEEvent = useCallback((ev: RIOUploadEvent) => {
    const dev = ev.device;
    if (!dev) return;

    setDeviceProgress((prev) => {
      const cur = prev[dev] ?? { phase: "pending", message: "" };
      switch (ev.event) {
        case "link_ready":
          return { ...prev, [dev]: { ...cur, url: ev.url, message: cur.message || "Preparing…" } };
        case "discovering":
          return { ...prev, [dev]: { ...cur, phase: "discovering", message: ev.message ?? "Discovering…" } };
        case "compressing":
          return { ...prev, [dev]: { ...cur, phase: "compressing", message: ev.message ?? "Compressing…" } };
        case "uploading":
          return { ...prev, [dev]: { ...cur, phase: "uploading", message: ev.message ?? "Uploading…" } };
        case "done":
          return { ...prev, [dev]: {
            phase: "done",
            message: ev.message ?? "Upload queued",
            url: ev.url ?? cur.url,
            filename: ev.filename,
            request_uuid: ev.request_uuid,
          }};
        case "error":
          return { ...prev, [dev]: { ...cur, phase: "error", message: ev.message ?? "Failed" } };
        default:
          return prev;
      }
    });
  }, []);

  async function handleDiscover() {
    if (!selectedProject || selectedDevices.length === 0 || !startTime || !endTime) return;
    setPreviewLoading(true);
    setPreviewError("");
    setPreviewBags(null);
    try {
      const startEpoch = localDatetimeToEpoch(startTime, selectedTz);
      const endEpoch = localDatetimeToEpoch(endTime, selectedTz);

      if (endEpoch <= startEpoch) {
        setPreviewError("End time must be after start time");
        return;
      }
      if (endEpoch - startEpoch > 86400) {
        setPreviewError("Time range cannot exceed 24 hours");
        return;
      }

      const result = await discoverRIOBags({
        project_guid: selectedProject.guid,
        device_name: selectedDevices[0],
        start_time_epoch: startEpoch,
        end_time_epoch: endEpoch,
      });
      setPreviewBags(result.bags);
    } catch (e: unknown) {
      setPreviewError(e instanceof Error ? e.message : "Discovery failed");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleUpload() {
    if (!canSubmit || !selectedProject) return;

    const startEpoch = localDatetimeToEpoch(startTime, selectedTz);
    const endEpoch = localDatetimeToEpoch(endTime, selectedTz);

    if (endEpoch <= startEpoch) {
      setMsg("End time must be after start time");
      setStatus("error");
      return;
    }
    if (endEpoch - startEpoch > 86400) {
      setMsg("Time range cannot exceed 24 hours");
      setStatus("error");
      return;
    }

    // Reset state
    esRef.current?.close();
    setStatus("uploading");
    setMsg("Starting parallel uploads…");
    const initialProgress: Record<string, DeviceProgress> = {};
    for (const d of selectedDevices) {
      initialProgress[d] = { phase: "pending", message: "Queued" };
    }
    setDeviceProgress(initialProgress);

    try {
      const { job_id } = await triggerRIOUpload({
        project_guid: selectedProject.guid,
        organization_guid: selectedProject.organization_guid,
        device_names: selectedDevices,
        start_time_epoch: startEpoch,
        end_time_epoch: endEpoch,
        max_upload_rate_mbps: uploadSpeedMbps,
        display_start: startTime,
        display_end: endTime,
        timezone_label: getTimezoneShortLabel(selectedTz),
        utc_offset_minutes: getTimezoneOffsetMinutes(selectedTz),
        site_code: selectedProject.name,
      });

      setMsg(`Job started — uploading from ${selectedDevices.length} AMR(s) at ${uploadSpeedMbps} MB/s each`);

      // Subscribe to SSE progress events
      esRef.current = subscribeUploadStatus(
        job_id,
        handleSSEEvent,
        () => {
          // job_done
          setStatus("done");
          setMsg("All uploads complete");
          onUploaded?.(`Upload triggered for ${selectedDevices.length} device(s)`);
        },
        () => {
          // SSE error (connection lost)
          setStatus("error");
          setMsg("Lost connection to upload progress stream");
        },
      );
    } catch (e: unknown) {
      setStatus("error");
      setMsg(e instanceof Error ? e.message : "Upload trigger failed");
    }
  }

  const configured = rioStatus?.configured ?? false;

  /** Icon + colour per phase. */
  function phaseIndicator(phase: DeviceProgress["phase"]) {
    switch (phase) {
      case "pending":    return <Loader2 size={12} className="animate-spin text-slate-500" />;
      case "discovering": return <Search size={12} className="text-blue-400" />;
      case "compressing": return <Archive size={12} className="text-amber-400" />;
      case "uploading":   return <ArrowUpCircle size={12} className="animate-pulse text-cyan-400" />;
      case "done":        return <CheckCircle size={12} className="text-emerald-400" />;
      case "error":       return <XCircle size={12} className="text-red-400" />;
    }
  }

  return (
    <div className="space-y-3">
      {/* ── Config status ────────────────────────────────── */}
      {rioStatus !== null && !configured && (
        <div className="flex items-center gap-2 text-xs rounded px-2.5 py-1.5 bg-amber-900/20 text-amber-400 border border-amber-800/30">
          <AlertTriangle size={12} />
          RIO is not configured. Run{" "}
          <code className="mx-1 bg-slate-800 px-1 rounded">rio auth login</code>{" "}
          on the host.
        </div>
      )}

      {/* ── Project selector ─────────────────────────────── */}
      <div className="relative" ref={projectDropdownRef}>
        <label className="block text-xs font-semibold text-slate-400 mb-1">
          <Server size={11} className="inline mr-1" />
          RIO Project
        </label>
        {loadingProjects ? (
          <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
            <Loader2 size={12} className="animate-spin" /> Loading projects…
          </div>
        ) : (
          <>
            <div
              className={clsx(
                "h-8 flex items-center gap-1.5 pl-2.5 pr-2 rounded-lg border text-xs font-medium transition-all",
                status === "uploading"
                  ? "opacity-40 cursor-not-allowed bg-white/[0.03] border-white/[0.06] text-slate-500"
                  : showProjectDropdown
                  ? "bg-blue-500/15 border-blue-500/40 text-blue-300 cursor-pointer"
                  : "bg-white/[0.05] border-white/[0.08] text-slate-300 hover:bg-white/[0.08] hover:border-white/[0.14] hover:text-slate-100 cursor-pointer"
              )}
              onClick={() => {
                if (status === "uploading") return;
                setShowProjectDropdown(v => !v);
                setProjectQuery("");
              }}
            >
              <Server size={11} className={showProjectDropdown ? "text-blue-400 shrink-0" : "text-slate-500 shrink-0"} />
              <span className="flex-1 truncate">
                {selectedProject?.name ?? (projects.length === 0 ? "No projects available" : "Select project")}
              </span>
              <ChevronDown size={10} className={clsx("transition-transform shrink-0", showProjectDropdown && "rotate-180")} />
            </div>

            {showProjectDropdown && (
              <div className="absolute top-full mt-1.5 left-0 z-50 w-full bg-[#0f172a] border border-white/[0.1] rounded-xl shadow-2xl shadow-black/50 flex flex-col">
                {/* Search */}
                <div className="p-2 border-b border-white/[0.06]">
                  <div className="relative">
                    <Search size={11} className="absolute left-2 top-1.5 text-slate-500 pointer-events-none" />
                    <input
                      autoFocus
                      type="text"
                      placeholder="Search projects..."
                      value={projectQuery}
                      onChange={e => setProjectQuery(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Escape") { setShowProjectDropdown(false); setProjectQuery(""); }
                        if (e.key === "Enter" && filteredProjects.length > 0) {
                          setSelectedProject(filteredProjects[0]);
                          setShowProjectDropdown(false);
                          setProjectQuery("");
                        }
                      }}
                      className="w-full h-6 pl-6 pr-2 rounded-md bg-white/[0.06] border border-white/[0.08] text-slate-200 placeholder-slate-600 text-xs focus:outline-none focus:border-blue-500/60"
                    />
                  </div>
                </div>
                {/* List */}
                <div className="max-h-60 overflow-y-auto overscroll-contain py-1">
                  {filteredProjects.length === 0 ? (
                    <p className="px-3 py-2 text-xs text-slate-500">No projects match</p>
                  ) : showGroups ? (
                    groupedProjects.map(([label, items]) => (
                      <div key={label}>
                        <div className="px-3 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500 border-b border-white/[0.05]">
                          {label || "Projects"}
                        </div>
                        {items.map(p => (
                          <button
                            key={p.guid}
                            onMouseDown={() => {
                              setSelectedProject(p);
                              setShowProjectDropdown(false);
                              setProjectQuery("");
                            }}
                            className={clsx(
                              "w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 hover:bg-white/[0.05] transition-colors",
                              p.guid === selectedProject?.guid ? "text-blue-400" : "text-slate-300"
                            )}
                          >
                            <span className="w-3 shrink-0">
                              {p.guid === selectedProject?.guid && <Check size={11} />}
                            </span>
                            <Server size={10} className={p.guid === selectedProject?.guid ? "text-blue-400" : "text-slate-600"} />
                            <span className="truncate">{p.name}</span>
                          </button>
                        ))}
                      </div>
                    ))
                  ) : (
                    filteredProjects.map(p => (
                      <button
                        key={p.guid}
                        onMouseDown={() => {
                          setSelectedProject(p);
                          setShowProjectDropdown(false);
                          setProjectQuery("");
                        }}
                        className={clsx(
                          "w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 hover:bg-white/[0.05] transition-colors",
                          p.guid === selectedProject?.guid ? "text-blue-400" : "text-slate-300"
                        )}
                      >
                        <span className="w-3 shrink-0">
                          {p.guid === selectedProject?.guid && <Check size={11} />}
                        </span>
                        <Server size={10} className={p.guid === selectedProject?.guid ? "text-blue-400" : "text-slate-600"} />
                        <span className="truncate">{p.name}</span>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Device multi-select ──────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs font-semibold text-slate-400">
            <MonitorSmartphone size={11} className="inline mr-1" />
            Online Devices
          </label>
          {devices.length > 0 && (
            <button
              onClick={selectAllDevices}
              className="text-[10px] text-blue-400 hover:text-blue-300"
            >
              {selectedDevices.length === devices.length
                ? "Deselect All"
                : "Select All"}
            </button>
          )}
        </div>
        {loadingDevices ? (
          <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
            <Loader2 size={12} className="animate-spin" /> Loading devices…
          </div>
        ) : devices.length === 0 ? (
          <p className="text-xs text-slate-500 py-1">
            {selectedProject
              ? "No online devices found"
              : "Select a project first"}
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
            {devices.map((d) => (
              <button
                key={d}
                onClick={() => toggleDevice(d)}
                disabled={status === "uploading"}
                className={`px-2 py-1 text-xs rounded-md border transition-colors ${
                  selectedDevices.includes(d)
                    ? "bg-blue-600/20 text-blue-400 border-blue-600/40"
                    : "text-slate-400 border-slate-700 hover:border-slate-600 hover:text-slate-300"
                }`}
              >
                {d}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Time range ───────────────────────────────────── */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs font-semibold text-slate-400">Time Range</label>
          <TimezoneSelector
            value={selectedTz}
            onChange={(tz) => { setSelectedTz(tz); setPreviewBags(null); }}
            systemTz={systemTz}
            disabled={status === "uploading"}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[10px] text-slate-500 mb-0.5">Start</label>
            <input
              type="datetime-local"
              value={startTime}
              onChange={(e) => { setStartTime(e.target.value); setPreviewBags(null); }}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500 transition-colors"
              disabled={status === "uploading"}
            />
          </div>
          <div>
            <label className="block text-[10px] text-slate-500 mb-0.5">End</label>
            <input
              type="datetime-local"
              value={endTime}
              onChange={(e) => { setEndTime(e.target.value); setPreviewBags(null); }}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500 transition-colors"
              disabled={status === "uploading"}
            />
          </div>
        </div>

        {/* UTC preview */}
        {startTime && endTime && selectedTz !== "UTC" && (
          <div className="text-[10px] text-slate-500 pl-0.5">
            UTC: {formatUtcPreview(startTime, selectedTz)} → {formatUtcPreview(endTime, selectedTz)}
          </div>
        )}
      </div>

      {/* ── Quick presets ──────────────────────────────────── */}
      <div className="flex flex-wrap gap-1.5">
        {[
          { label: "Last 10 min", mins: 10 },
          { label: "Last 30 min", mins: 30 },
          { label: "Last 1 hour", mins: 60 },
          { label: "Last 3 hours", mins: 180 },
        ].map(({ label, mins }) => (
          <button
            key={label}
            type="button"
            disabled={status === "uploading"}
            onClick={() => {
              const nowEpoch = Math.floor(Date.now() / 1000);
              setEndTime(epochToLocalDatetime(nowEpoch, selectedTz));
              setStartTime(epochToLocalDatetime(nowEpoch - mins * 60, selectedTz));
              setPreviewBags(null);
            }}
            className="px-2 py-1 text-[10px] rounded-md border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors"
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Discover preview ───────────────────────────── */}
      {selectedDevices.length === 1 && status !== "uploading" && (
        <div className="space-y-1.5">
          <button
            type="button"
            onClick={handleDiscover}
            disabled={previewLoading || !startTime || !endTime}
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40"
          >
            {previewLoading ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
            Discover bags on {selectedDevices[0]}
          </button>
          {previewError && (
            <p className="text-[10px] text-red-400">{previewError}</p>
          )}
          {previewBags !== null && !previewError && (
            <div className="text-[10px] rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2">
              {previewBags.length === 0 ? (
                <span className="text-amber-400">No bags found in this time range</span>
              ) : (
                <>
                  <span className="text-emerald-400">{previewBags.length} bag(s) found:</span>
                  <ul className="mt-1 space-y-0.5 text-slate-400 max-h-24 overflow-y-auto">
                    {previewBags.map((b) => (
                      <li key={b} className="font-mono truncate">{b.split("/").pop()}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Upload speed (per AMR) ───────────────────────── */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 mb-1">
          Upload Speed per AMR (MB/s)
        </label>
        <input
          type="number"
          min={1}
          max={200}
          value={uploadSpeedMbps}
          onChange={(e) => {
            const v = parseInt(e.target.value, 10);
            if (!isNaN(v)) setUploadSpeedMbps(Math.min(200, Math.max(1, v)));
          }}
          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500 transition-colors"
          disabled={status === "uploading"}
        />
        <p className="text-[10px] text-slate-500 mt-0.5">
          Each AMR uploads independently at this speed (1–200 MB/s, default 10)
        </p>
      </div>

      {/* ── Upload button ────────────────────────────────── */}
      <button
        onClick={handleUpload}
        disabled={!canSubmit}
        className="btn btn-primary w-full py-2.5 text-sm gap-2 disabled:opacity-40"
      >
        {status === "uploading" ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <Upload size={14} />
        )}
        {status === "uploading"
          ? "Uploading…"
          : `Upload from ${selectedDevices.length || 0} Device${
              selectedDevices.length !== 1 ? "s" : ""
            }`}
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
          {status === "uploading" && (
            <Loader2 size={14} className="animate-spin" />
          )}
          {msg}
        </div>
      )}

      {/* ── Per-device live progress ─────────────────────── */}
      {Object.keys(deviceProgress).length > 0 && (
        <div className="space-y-1.5">
          {Object.entries(deviceProgress).map(([device, dp]) => (
            <div
              key={device}
              className={`flex items-center justify-between rounded-lg px-3 py-2 text-xs border ${
                dp.phase === "done"
                  ? "bg-emerald-900/10 border-emerald-800/30"
                  : dp.phase === "error"
                  ? "bg-red-900/10 border-red-800/30"
                  : "bg-slate-800/50 border-slate-700/50"
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                {phaseIndicator(dp.phase)}
                <span className="font-mono font-semibold text-slate-200">{device}</span>
                <span className="truncate text-slate-400">{dp.message}</span>
              </div>
              {dp.url && (
                <a
                  href={dp.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-blue-400 hover:text-blue-300 shrink-0 ml-2"
                >
                  Console <ExternalLink size={10} />
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
