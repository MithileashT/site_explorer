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

import React, { useCallback, useRef, useState } from "react";
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
} from "lucide-react";
import clsx from "clsx";
import { uploadBag, extractBagTrajectory, listBagTopics } from "@/lib/api";
import type { TrajectoryPoint, BagTopicInfo } from "@/lib/types";

// ── Props ──────────────────────────────────────────────────────────────────────

interface Props {
  /** Currently selected site in the parent page — used as default in the picker. */
  currentSiteId: string;
  /** Available sites from the sitemap service. */
  sites: { id: string; name: string }[];
  /** Called after a trajectory is successfully extracted. */
  onTrajectoryLoaded: (points: TrajectoryPoint[], bagName: string, siteId: string, frameId: string | null) => void;
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

  // Process state
  const [phase,   setPhase]   = useState<UploadPhase>("idle");
  const [message, setMessage] = useState("");
  const [progress, setProgress] = useState(0); // 0–100

  // Topic picker state
  const [bagPath,       setBagPath]       = useState<string | null>(null);
  const [availableTopics, setAvailableTopics] = useState<BagTopicInfo[]>([]);
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Keep selectedSiteId in sync when parent changes site during idle state
  React.useEffect(() => {
    if (phase === "idle") setSelectedSiteId(currentSiteId);
  }, [currentSiteId, phase]);

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

  const _handleTrajectoryResult = useCallback((traj: { points: TrajectoryPoint[]; topic: string; frame_id: string | null; error: string | null; raw_count?: number; total_points: number }) => {
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
    onTrajectoryLoaded(traj.points, bagFile?.name ?? "bag", selectedSiteId, traj.frame_id);
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
        const resp = await listBagTopics(bag_path);
        const poseTopics = resp.topics.filter(t => t.is_pose);
        setAvailableTopics(resp.topics);

        if (poseTopics.length > 1) {
          // Multiple pose topics — show picker and wait for user selection
          setSelectedTopic(poseTopics[0].topic);
          setPhase("picking");
          setProgress(55);
          setMessage(`Found ${poseTopics.length} pose topics — select one to extract.`);
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
        "absolute bottom-0 left-0 right-0 z-20 transition-all duration-200",
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

            {/* Site picker */}
            <div className="relative">
              <button
                onClick={() => setShowSitePicker(v => !v)}
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

              {showSitePicker && (
                <div className="absolute bottom-full mb-1 right-0 z-30 min-w-[180px] bg-[#161b22] border border-[#30363d] rounded-xl shadow-2xl shadow-black/70 py-1">
                  <div className="px-3 py-1.5 text-[11px] text-[#8b949e] uppercase tracking-wider border-b border-[#30363d] mb-1 font-medium">
                    Select site
                  </div>
                  <div className="max-h-48 overflow-y-auto overscroll-contain">
                    {sites.map(s => (
                      <button
                        key={s.id}
                        onClick={() => { setSelectedSiteId(s.id); setShowSitePicker(false); }}
                        className={clsx(
                          "w-full text-left px-3 py-2 text-[13px] flex items-center gap-2 hover:bg-[#00e5ff]/10 transition-colors",
                          s.id === selectedSiteId ? "text-[#00e5ff] font-medium" : "text-[#e6edf3]"
                        )}
                      >
                        <MapPin size={10} className={s.id === selectedSiteId ? "text-[#00e5ff]" : "text-[#484f58]"} />
                        <span className="truncate">{s.id}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
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

          {/* Topic picker — shown when multiple pose topics found */}
          {phase === "picking" && availableTopics.filter(t => t.is_pose).length > 0 && (
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
              <button
                onClick={handleClear}
                className="flex items-center gap-1.5 text-[#8b949e] hover:text-red-400 transition-colors text-[12px]"
              >
                <Trash2 size={11} />
                Clear
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
