"use client";

/**
 * BagUploadPanel
 * ──────────────
 * Collapsible bottom panel on the Site Map page that lets users:
 *   1. Pick a ROS bag file (.bag / .db3)
 *   2. Choose the target site (defaults to the currently loaded site)
 *   3. Upload the bag and extract an AMR trajectory from it
 *   4. Notify the parent with the trajectory points so they can be rendered
 *      on the SiteMapCanvas
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Upload,
  ChevronUp,
  ChevronDown,
  X,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Route,
  MapPin,
  Trash2,
  Radio,
  Search,
  GitBranch,
} from "lucide-react";
import clsx from "clsx";
import { uploadBag, extractBagTrajectory, listBagTopics, listNavTopics, getSiteBranchInfo } from "@/lib/api";
import type { TrajectoryPoint, BagTopicInfo, NavTopicStatus, BranchInfo } from "@/lib/types";

// ── Props ──────────────────────────────────────────────────────────────────────

interface Props {
  /** Currently selected site in the parent page — used as default in the picker. */
  currentSiteId: string;
  /** Available sites from the sitemap service. */
  sites: { id: string; name: string }[];
  /** Called after a trajectory is successfully extracted. */
  onTrajectoryLoaded: (
    points: TrajectoryPoint[],
    bagName: string,
    siteId: string,
    frameId: string | null,
    bagTimeRange: { start: number; end: number } | null,
  ) => void;
  /** Called when the user explicitly clears the current trajectory. */
  onTrajectoryClear: () => void;
  /** Whether a trajectory is currently rendered on the canvas. */
  hasTrajectory: boolean;
}

// ── Upload state machine ───────────────────────────────────────────────────────

type UploadPhase =
  | "idle"
  | "uploading"
  | "picking"
  | "extracting"
  | "done"
  | "error";

// ── Component ──────────────────────────────────────────────────────────────────

export default function BagUploadPanel({
  currentSiteId,
  sites,
  onTrajectoryLoaded,
  onTrajectoryClear,
  hasTrajectory,
}: Props) {
  // Panel collapsed / expanded
  const [expanded, setExpanded] = useState(false);

  // Form state
  const [selectedSiteId, setSelectedSiteId] = useState(currentSiteId);
  const [bagFile,        setBagFile]        = useState<File | null>(null);
  const [showSitePicker, setShowSitePicker] = useState(false);
  const [sitePickerQuery, setSitePickerQuery] = useState("");

  // Branch info for the selected site
  const [siteBranchInfo, setSiteBranchInfo] = useState<BranchInfo | null>(null);
  const [siteBranchLoading, setSiteBranchLoading] = useState(false);

  // Ref for outside-click on site picker
  const sitePickerRef = useRef<HTMLDivElement>(null);

  // Process state
  const [phase,   setPhase]   = useState<UploadPhase>("idle");
  const [message, setMessage] = useState("");
  const [progress, setProgress] = useState(0); // 0–100

  // Topic picker state
  const [bagPath,       setBagPath]       = useState<string | null>(null);
  const [availableTopics, setAvailableTopics] = useState<BagTopicInfo[]>([]);
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);

  // Navigation topic status
  const [navTopics, setNavTopics] = useState<NavTopicStatus[]>([]);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Keep selectedSiteId in sync when parent changes site during idle state
  useEffect(() => {
    if (phase === "idle") setSelectedSiteId(currentSiteId);
  }, [currentSiteId, phase]);

  // Fetch branch info whenever siteId changes
  useEffect(() => {
    if (!selectedSiteId) { setSiteBranchInfo(null); return; }
    setSiteBranchLoading(true);
    getSiteBranchInfo(selectedSiteId)
      .then(setSiteBranchInfo)
      .catch(() => setSiteBranchInfo(null))
      .finally(() => setSiteBranchLoading(false));
  }, [selectedSiteId]);

  // Close site picker on outside click
  useEffect(() => {
    if (!showSitePicker) return;
    function handleOutside(e: MouseEvent) {
      if (sitePickerRef.current && !sitePickerRef.current.contains(e.target as Node)) {
        setShowSitePicker(false);
        setSitePickerQuery("");
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [showSitePicker]);

  // ── File selection ──────────────────────────────────────────────────────────

  const handleFileChange = useCallback((
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = e.target.files?.[0] ?? null;
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (ext !== "bag" && ext !== "db3") {
      setPhase("error");
      setMessage("Only .bag and .db3 files are supported.");
      return;
    }
    setBagFile(file);
    setPhase("idle");
    setMessage("");
    // Auto-expand panel when a file is selected
    setExpanded(true);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (ext !== "bag" && ext !== "db3") {
      setPhase("error");
      setMessage("Only .bag and .db3 files are supported.");
      return;
    }
    setBagFile(file);
    setPhase("idle");
    setMessage("");
    // Auto-expand panel on drop
    setExpanded(true);
  }, []);

  // ── Upload & extract ────────────────────────────────────────────────────────

  const _handleTrajectoryResult = useCallback((traj: { points: TrajectoryPoint[]; topic: string; frame_id: string | null; error: string | null; raw_count?: number; total_points: number; bag_start_time?: number | null; bag_end_time?: number | null }) => {
    if (!traj.points.length) {
      setPhase("error");
      setMessage(traj.error ?? "No trajectory data found in bag.");
      return;
    }

    const frameWarning = traj.frame_id && traj.frame_id.toLowerCase().includes("odom")
      ? ` ⚠ odom frame — may not align with map`
      : "";

    const cleanedInfo = traj.raw_count && traj.raw_count !== traj.total_points
      ? ` (${traj.raw_count} raw → ${traj.total_points} cleaned)`
      : "";

    setPhase("done");
    setMessage(
      `${traj.points.length.toLocaleString()} poses from ${traj.topic}`
      + (traj.frame_id ? ` [${traj.frame_id}]` : "")
      + cleanedInfo
      + frameWarning
      + (traj.error ? ` (⚠ ${traj.error})` : "")
    );

    // Build bag time range from the API response
    const bagTimes = (traj.bag_start_time != null && traj.bag_end_time != null)
      ? { start: traj.bag_start_time, end: traj.bag_end_time }
      : null;

    onTrajectoryLoaded(traj.points, bagFile?.name ?? "bag", selectedSiteId, traj.frame_id, bagTimes);
  }, [onTrajectoryLoaded, bagFile, selectedSiteId]);

  const handleUpload = useCallback(async () => {
    if (!bagFile) return;
    if (!selectedSiteId) {
      setPhase("error");
      setMessage("Please select a site before extracting trajectory.");
      setShowSitePicker(true);
      return;
    }

    try {
      // Phase 1: upload
      setPhase("uploading");
      setProgress(20);
      setMessage(`Uploading ${bagFile.name}…`);

      const { bag_path } = await uploadBag(bagFile);
      setBagPath(bag_path);
      setProgress(50);

      // Phase 2: fetch topics
      setMessage("Scanning topics…");
      try {
        const [topicsResp, navResp] = await Promise.all([
          listBagTopics(bag_path),
          listNavTopics(bag_path),
        ]);
        setAvailableTopics(topicsResp.topics);
        setNavTopics(navResp.nav_topics);

        // Find available nav topics for the picker
        const availableNav = navResp.nav_topics.filter(nt => nt.available);
        if (availableNav.length > 0) {
          setSelectedTopic(availableNav[0].topic);
          setPhase("picking");
          setProgress(55);
          setMessage(`Found ${availableNav.length} of ${navResp.nav_topics.length} navigation topics — select one to extract.`);
          return;
        }

        // Fallback to pose topic picker if no nav topics available
        const poseTopics = topicsResp.topics.filter(t => t.is_pose);
        if (poseTopics.length > 1) {
          setSelectedTopic(poseTopics[0].topic);
          setPhase("picking");
          setProgress(55);
          setMessage(`No navigation topics found. ${poseTopics.length} pose topics available.`);
          return;
        }
      } catch {
        // If topics listing fails, proceed without topic picker
      }

      // Phase 3: extract trajectory (auto — no topic selection needed)
      setPhase("extracting");
      setMessage("Extracting trajectory…");
      setProgress(70);

      const traj = await extractBagTrajectory(bag_path, selectedSiteId);
      setProgress(100);
      _handleTrajectoryResult(traj);
    } catch (err: unknown) {
      setPhase("error");
      setMessage(err instanceof Error ? err.message : "Upload failed.");
    }
  }, [bagFile, selectedSiteId, _handleTrajectoryResult]);

  const handleExtractWithTopic = useCallback(async () => {
    if (!bagPath || !selectedSiteId) return;
    try {
      setPhase("extracting");
      setMessage("Extracting trajectory…");
      setProgress(70);

      const traj = await extractBagTrajectory(
        bagPath, selectedSiteId, 4000, selectedTopic ?? undefined
      );
      setProgress(100);
      _handleTrajectoryResult(traj);
    } catch (err: unknown) {
      setPhase("error");
      setMessage(err instanceof Error ? err.message : "Extraction failed.");
    }
  }, [bagPath, selectedSiteId, selectedTopic, _handleTrajectoryResult]);

  // ── Clear ───────────────────────────────────────────────────────────────────

  const handleClear = useCallback(() => {
    setBagFile(null);
    setBagPath(null);
    setAvailableTopics([]);
    setSelectedTopic(null);
    setNavTopics([]);
    setPhase("idle");
    setMessage("");
    setProgress(0);
    onTrajectoryClear();
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [onTrajectoryClear]);

  // ── Derived ─────────────────────────────────────────────────────────────────

  const busy = phase === "uploading" || phase === "extracting";
  const canUpload = !!bagFile && !!selectedSiteId && !busy && phase !== "picking";

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div
      className={clsx(
        "shrink-0 transition-all duration-200",
        "border-t-2 bg-[#0a0f1a]",
        phase === "done"
          ? "border-emerald-500/50"
          : phase === "error"
          ? "border-red-500/40"
          : "border-[#00e5ff]/50",
      )}
    >
      {/* ── Collapsed / header bar ─────────────────────────────────── */}
      <div
        className={clsx(
          "flex items-center gap-2.5 px-4 h-11 cursor-pointer select-none border-b border-[#1e2842]",
          phase === "done"
            ? "bg-emerald-950/60"
            : phase === "error"
            ? "bg-red-950/50"
            : "bg-[#0e1628]"
        )}
        onClick={() => setExpanded(v => !v)}
      >
        <div className={clsx(
          "w-6 h-6 rounded flex items-center justify-center shrink-0",
          phase === "done"
            ? "bg-emerald-500/20 border border-emerald-500/40"
            : "bg-[#00e5ff]/20 border border-[#00e5ff]/50"
        )}>
          <Upload size={12} className={phase === "done" ? "text-emerald-400" : "text-[#00e5ff]"} />
        </div>
        <span className={clsx(
          "text-sm font-semibold",
          phase === "done" ? "text-emerald-300" : "text-[#e6edf3]"
        )}>
          ROS Bag Upload
        </span>

        {/* Status badge */}
        {phase === "done" && (
          <span className="flex items-center gap-1 text-[11px] text-emerald-300 bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.5 rounded-full font-medium">
            <CheckCircle2 size={10} />
            Trajectory loaded
          </span>
        )}
        {phase === "error" && (
          <span className="flex items-center gap-1 text-[11px] text-red-300 bg-red-500/15 border border-red-500/30 px-2 py-0.5 rounded-full font-medium">
            <AlertCircle size={10} />
            Error
          </span>
        )}
        {busy && (
          <span className="flex items-center gap-1 text-[11px] text-[#00e5ff] font-medium">
            <Loader2 size={10} className="animate-spin" />
            {phase === "uploading" ? "Uploading…" : "Extracting…"}
          </span>
        )}

        {/* Right controls: clear button + chevron, grouped together */}
        <div className="ml-auto flex items-center gap-1">
          {hasTrajectory && (
            <button
              onClick={e => { e.stopPropagation(); handleClear(); }}
              title="Clear trajectory"
              className="p-1 rounded text-[#8b949e] hover:text-red-400 hover:bg-red-500/10 transition-colors"
            >
              <Trash2 size={13} />
            </button>
          )}
          <div className={clsx("p-1 text-[#8b949e] transition-transform duration-200", expanded ? "rotate-180" : "")}>
            {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </div>
        </div>
      </div>

      {/* ── Expanded body ───────────────────────────────────────────── */}
      {expanded && (
        <div className="px-4 pb-4 pt-3 flex flex-col gap-3 bg-[#0a0f1a]">
          {/* Drop-zone / file selector row */}
          <div className="flex items-stretch gap-2.5">
            {/* Drop zone */}
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={clsx(
                "flex-1 flex items-center gap-2.5 px-3.5 py-2.5 rounded-lg cursor-pointer transition-all",
                bagFile
                  ? "border-[1.5px] border-solid border-emerald-400/60 bg-emerald-500/10"
                  : "border-[1.5px] border-dashed border-[#00e5ff]/50 bg-[#1a1a2e] hover:border-[#00e5ff]/80 hover:bg-[#1a1a2e]/80"
              )}
            >
              <Upload size={14} className={bagFile ? "text-emerald-400" : "text-[#00e5ff]"} />
              <div className="min-w-0 flex-1">
                {bagFile ? (
                  <>
                    <p className="text-[13px] font-medium text-emerald-300 truncate">{bagFile.name}</p>
                    <p className="text-[11px] text-[#8b949e]">
                      {(bagFile.size / (1024 * 1024)).toFixed(1)} MB
                    </p>
                  </>
                ) : (
                  <p className="text-[13px] text-[#c9d1d9]">
                    Click or drop a <code className="text-[#00e5ff] font-semibold">.bag</code> / <code className="text-[#00e5ff] font-semibold">.db3</code> file
                  </p>
                )}
              </div>
              {bagFile && (
                <button
                  onClick={e => { e.stopPropagation(); handleClear(); }}
                  className="text-[#8b949e] hover:text-red-400 transition-colors shrink-0"
                >
                  <X size={13} />
                </button>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".bag,.db3"
              className="hidden"
              onChange={handleFileChange}
            />

            {/* Site picker — searchable combobox */}
            <div className="relative" ref={sitePickerRef}>
              <button
                onClick={() => {
                  setShowSitePicker(v => !v);
                  setSitePickerQuery("");
                }}
                className={clsx(
                  "h-full flex items-center gap-1.5 px-3 rounded-lg border text-[13px] font-medium transition-all",
                  showSitePicker
                    ? "bg-[#00e5ff]/10 border-[#00e5ff]/50 text-[#00e5ff]"
                    : "bg-[#1a1a2e] border-[#30363d] text-[#e6edf3] hover:border-[#00e5ff]/40"
                )}
              >
                <MapPin size={11} className={showSitePicker ? "text-[#00e5ff]" : "text-[#8b949e]"} />
                <span className="max-w-[100px] truncate">{selectedSiteId || "Site"}</span>
                <ChevronDown size={10} className={clsx("transition-transform", showSitePicker && "rotate-180")} />
              </button>

              {showSitePicker && (() => {
                const q = sitePickerQuery.toLowerCase().trim();
                const filtered = q
                  ? sites.filter(s => s.id.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
                  : sites;
                return (
                  <div className="absolute bottom-full mb-1 right-0 z-30 w-56 bg-[#161b22] border border-[#30363d] rounded-xl shadow-2xl shadow-black/70 flex flex-col">
                    {/* Search input */}
                    <div className="p-2 border-b border-[#30363d]">
                      <div className="relative">
                        <Search size={11} className="absolute left-2 top-1.5 text-[#8b949e] pointer-events-none" />
                        <input
                          autoFocus
                          type="text"
                          placeholder="Search sites..."
                          value={sitePickerQuery}
                          onChange={e => setSitePickerQuery(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === "Escape") { setShowSitePicker(false); setSitePickerQuery(""); }
                            if (e.key === "Enter" && filtered.length > 0) {
                              setSelectedSiteId(filtered[0].id);
                              setShowSitePicker(false);
                              setSitePickerQuery("");
                            }
                          }}
                          className="w-full h-6 pl-6 pr-2 rounded-md bg-[#0d1117] border border-[#30363d] text-[#e6edf3] placeholder-[#484f58] text-xs focus:outline-none focus:border-[#00e5ff]/50"
                        />
                      </div>
                    </div>
                    {/* Site list */}
                    <div className="max-h-48 overflow-y-auto overscroll-contain py-1">
                      {filtered.length === 0 ? (
                        <p className="px-3 py-2 text-xs text-[#8b949e]">No sites match</p>
                      ) : (
                        filtered.map(s => (
                          <button
                            key={s.id}
                            onMouseDown={() => { setSelectedSiteId(s.id); setShowSitePicker(false); setSitePickerQuery(""); }}
                            className={clsx(
                              "w-full text-left px-3 py-1.5 text-[13px] flex items-center gap-2 hover:bg-[#00e5ff]/10 transition-colors",
                              s.id === selectedSiteId ? "text-[#00e5ff] font-medium" : "text-[#e6edf3]"
                            )}
                          >
                            <MapPin size={10} className={s.id === selectedSiteId ? "text-[#00e5ff]" : "text-[#484f58]"} />
                            <span className="truncate">{s.id}</span>
                          </button>
                        ))
                      )}
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Upload button */}
            <button
              onClick={handleUpload}
              disabled={!canUpload}
              className={clsx(
                "flex items-center gap-1.5 px-4 rounded-lg text-[13px] font-bold transition-all shrink-0",
                canUpload
                  ? "bg-[#00e5ff] hover:bg-[#33eaff] text-[#030b14] shadow-[0_0_12px_rgba(0,229,255,0.35)] hover:shadow-[0_0_18px_rgba(0,229,255,0.5)]"
                  : "bg-[#1c2636] text-[#4a5568] cursor-not-allowed"
              )}
            >
              {busy ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Route size={12} />
              )}
              {busy ? (phase === "uploading" ? "Uploading" : "Extracting") : "Extract Path"}
            </button>
          </div>

          {/* Branch info badge — shown once a site is selected */}
          {selectedSiteId && (
            <div className="flex items-center gap-2 text-[11px]">
              <GitBranch size={11} className="text-[#8b949e] shrink-0" />
              {siteBranchLoading ? (
                <span className="text-[#8b949e]">Loading branch…</span>
              ) : siteBranchInfo ? (
                <>
                  <span
                    className={clsx(
                      "px-1.5 py-0.5 rounded font-mono font-medium",
                      siteBranchInfo.is_site_specific
                        ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                        : "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                    )}
                  >
                    {siteBranchInfo.branch}
                  </span>
                  {!siteBranchInfo.is_site_specific && (
                    <span className="text-amber-400/80">No dedicated branch — using main</span>
                  )}
                  {siteBranchInfo.is_override && (
                    <span className="text-amber-400/80">(manual override)</span>
                  )}
                </>
              ) : (
                <span className="text-[#8b949e]">Branch unavailable</span>
              )}
            </div>
          )}

          {/* Progress / status bar */}
          {(busy || phase === "done" || phase === "error" || phase === "picking") && (
            <div className="space-y-2 p-2.5 rounded-lg bg-[#161b22] border border-[#30363d]">
              {busy && (
                <div className="w-full h-1.5 bg-[#2d2d3d] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[#00e5ff] rounded-full transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              )}
              <div className={clsx(
                "flex items-center gap-1.5 text-[13px] font-medium",
                phase === "error" ? "text-red-400"
                  : phase === "done" ? "text-emerald-300"
                  : phase === "picking" ? "text-[#00e5ff]"
                  : "text-[#c9d1d9]"
              )}>
                {phase === "error"   && <AlertCircle size={12} />}
                {phase === "done"    && <CheckCircle2 size={12} />}
                {phase === "picking" && <Radio size={12} />}
                {busy               && <Loader2 size={12} className="animate-spin" />}
                <span>{message}</span>
              </div>
            </div>
          )}

          {/* Topic picker — shown after upload when navigation topics detected */}
          {phase === "picking" && navTopics.length > 0 && (
            <div className="space-y-2.5 p-3 rounded-lg bg-[#161b22] border border-[#00e5ff]/30">
              <div className="flex items-center justify-between">
                <div className="text-[11px] text-[#00e5ff] font-semibold uppercase tracking-wider">
                  Select Navigation Topic
                </div>
                <span className="text-[10px] text-[#8b949e]">
                  {navTopics.filter(t => t.available).length}/{navTopics.length} available
                </span>
              </div>

              {/* Warning for cmd_vel */}
              {selectedTopic === "/cmd_vel" && (
                <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-amber-500/10 border border-amber-500/30 text-[11px] text-amber-300">
                  <AlertCircle size={11} />
                  <span>/cmd_vel has velocity data only — no position for trajectory</span>
                </div>
              )}

              <div className="space-y-1.5 max-h-52 overflow-y-auto">
                {navTopics.map(nt => (
                  <label
                    key={nt.topic}
                    className={clsx(
                      "flex items-center gap-2.5 px-3 py-2 rounded-md transition-all text-[13px]",
                      !nt.available
                        ? "opacity-40 cursor-not-allowed bg-[#0d1117] border border-[#21262d]"
                        : selectedTopic === nt.topic
                        ? "cursor-pointer bg-[#00e5ff]/10 border border-[#00e5ff]/40 text-[#e6edf3]"
                        : "cursor-pointer bg-[#0d1117] border border-[#30363d] text-[#c9d1d9] hover:border-[#00e5ff]/30"
                    )}
                  >
                    <input
                      type="radio"
                      name="nav-topic"
                      value={nt.topic}
                      checked={selectedTopic === nt.topic}
                      onChange={() => setSelectedTopic(nt.topic)}
                      disabled={!nt.available}
                      className="accent-[#00e5ff] w-3.5 h-3.5"
                    />
                    <span className="shrink-0 text-[12px]">{nt.available ? "✅" : "❌"}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={clsx(
                          "font-semibold text-[10px] px-1.5 py-0.5 rounded",
                          nt.available
                            ? "bg-[#00e5ff]/15 text-[#00e5ff]"
                            : "bg-[#21262d] text-[#8b949e]"
                        )}>
                          {nt.role}
                        </span>
                        <span className="font-mono text-[11px] text-[#8b949e] truncate">{nt.topic}</span>
                      </div>
                    </div>
                    {nt.available && nt.count > 0 && (
                      <span className="text-[10px] text-[#8b949e] bg-[#21262d] px-1.5 py-0.5 rounded shrink-0">
                        {nt.count.toLocaleString()} msgs
                      </span>
                    )}
                  </label>
                ))}
              </div>
              <button
                onClick={handleExtractWithTopic}
                disabled={!selectedTopic}
                className={clsx(
                  "w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-bold transition-all",
                  selectedTopic
                    ? "bg-[#00e5ff] hover:bg-[#33eaff] text-[#030b14] shadow-[0_0_10px_rgba(0,229,255,0.3)]"
                    : "bg-[#1c2636] text-[#4a5568] cursor-not-allowed"
                )}
              >
                <Route size={12} />
                Extract with selected topic
              </button>
            </div>
          )}

          {/* Fallback: old pose topic picker when no nav topics found */}
          {phase === "picking" && navTopics.length === 0 && availableTopics.filter(t => t.is_pose).length > 0 && (
            <div className="space-y-2.5 p-3 rounded-lg bg-[#161b22] border border-[#00e5ff]/30">
              <div className="text-[11px] text-[#00e5ff] font-semibold uppercase tracking-wider">
                Select pose topic
              </div>
              <div className="space-y-1.5 max-h-44 overflow-y-auto">
                {availableTopics.filter(t => t.is_pose).map(t => (
                  <label
                    key={t.topic}
                    className={clsx(
                      "flex items-center gap-2.5 px-3 py-2 rounded-md cursor-pointer transition-all text-[13px]",
                      selectedTopic === t.topic
                        ? "bg-[#00e5ff]/10 border border-[#00e5ff]/40 text-[#e6edf3]"
                        : "bg-[#0d1117] border border-[#30363d] text-[#c9d1d9] hover:border-[#00e5ff]/30"
                    )}
                  >
                    <input
                      type="radio"
                      name="pose-topic"
                      value={t.topic}
                      checked={selectedTopic === t.topic}
                      onChange={() => setSelectedTopic(t.topic)}
                      className="accent-[#00e5ff] w-3.5 h-3.5"
                    />
                    <span className="flex-1 truncate font-mono text-[12px]">{t.topic}</span>
                    {t.count > 0 && (
                      <span className="text-[10px] text-[#8b949e] bg-[#21262d] px-2 py-0.5 rounded font-medium">
                        {t.count.toLocaleString()} msgs
                      </span>
                    )}
                  </label>
                ))}
              </div>
              <button
                onClick={handleExtractWithTopic}
                disabled={!selectedTopic}
                className={clsx(
                  "w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-bold transition-all",
                  selectedTopic
                    ? "bg-[#00e5ff] hover:bg-[#33eaff] text-[#030b14] shadow-[0_0_10px_rgba(0,229,255,0.3)]"
                    : "bg-[#1c2636] text-[#4a5568] cursor-not-allowed"
                )}
              >
                <Route size={12} />
                Extract with selected topic
              </button>
            </div>
          )}

          {/* Trajectory summary when done */}
          {phase === "done" && hasTrajectory && (
            <div className="flex items-center justify-between text-[12px] px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30">
              <div className="flex items-center gap-2 text-emerald-300 font-medium">
                <Route size={12} />
                <span>Trajectory visible on map</span>
              </div>
              <div className="flex items-center gap-2">
                {bagPath && navTopics.length > 0 && (
                  <button
                    onClick={() => {
                      const availableNav = navTopics.filter(nt => nt.available);
                      if (availableNav.length > 0) {
                        setSelectedTopic(availableNav[0].topic);
                      }
                      setPhase("picking");
                      setMessage("Select a different topic to extract.");
                    }}
                    className="flex items-center gap-1.5 text-[#00e5ff] hover:text-[#33eaff] transition-colors text-[12px]"
                  >
                    <Radio size={11} />
                    Change Topic
                  </button>
                )}
                <button
                  onClick={handleClear}
                  className="flex items-center gap-1.5 text-[#8b949e] hover:text-red-400 transition-colors text-[12px]"
                >
                  <Trash2 size={11} />
                  Clear
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
