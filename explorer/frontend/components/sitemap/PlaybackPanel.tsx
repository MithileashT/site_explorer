"use client";

/**
 * PlaybackPanel
 * ─────────────
 * In-UI playback controls for ROS bag trajectory replay:
 *   - Play / Pause / Stop buttons
 *   - Speed selector (0.25x, 0.5x, 1x, 2x, 5x)
 *   - Draggable scrubber bar (mouse + touch) mapped to trajectory timestamps
 *   - Elapsed / total time display
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Play, Pause, Square, SkipBack } from "lucide-react";
import clsx from "clsx";
import type { TrajectoryPoint } from "@/lib/types";

interface Props {
  trajectory: TrajectoryPoint[];
  playbackIndex: number;
  isPlaying: boolean;
  speed: number;
  onPlayPause: () => void;
  onStop: () => void;
  onSeek: (index: number) => void;
  onSpeedChange: (speed: number) => void;
}

const SPEEDS = [0.25, 0.5, 1, 2, 5];

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function PlaybackPanel({
  trajectory,
  playbackIndex,
  isPlaying,
  speed,
  onPlayPause,
  onStop,
  onSeek,
  onSpeedChange,
}: Props) {
  const scrubberRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  const total = trajectory.length;

  const seekFromClientX = useCallback(
    (clientX: number) => {
      const bar = scrubberRef.current;
      if (!bar || total < 2) return;
      const rect = bar.getBoundingClientRect();
      const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      const idx = Math.round(frac * (total - 1));
      onSeek(idx);
    },
    [total, onSeek]
  );

  // ── Mouse handlers ──────────────────────────────────────────────────────────

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setDragging(true);
      seekFromClientX(e.clientX);
    },
    [seekFromClientX]
  );

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      e.preventDefault();
      seekFromClientX(e.clientX);
    };
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove, { passive: false });
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, seekFromClientX]);

  // ── Touch handlers ──────────────────────────────────────────────────────────

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      e.preventDefault();
      setDragging(true);
      if (e.touches[0]) seekFromClientX(e.touches[0].clientX);
    },
    [seekFromClientX]
  );

  useEffect(() => {
    if (!dragging) return;
    const onTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      if (e.touches[0]) seekFromClientX(e.touches[0].clientX);
    };
    const onTouchEnd = () => setDragging(false);
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd);
    window.addEventListener("touchcancel", onTouchEnd);
    return () => {
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [dragging, seekFromClientX]);

  if (total < 2) return null;

  const t0 = trajectory[0].timestamp;
  const tEnd = trajectory[total - 1].timestamp;
  const duration = tEnd - t0;
  const elapsed = playbackIndex < total
    ? trajectory[playbackIndex].timestamp - t0
    : duration;
  const progress = total > 1 ? playbackIndex / (total - 1) : 0;
  // Clamp thumb position so it stays fully inside the track
  const thumbPct = Math.max(0, Math.min(100, progress * 100));

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-[#0d1117] border-t-2 border-[#00e5ff]/40 select-none shadow-xl shadow-black/60">
      {/* Transport controls */}
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          onClick={onStop}
          title="Reset to start"
          className="p-1.5 rounded hover:bg-[#21262d] text-[#c9d1d9] hover:text-white transition-colors"
        >
          <SkipBack size={14} />
        </button>
        <button
          onClick={onPlayPause}
          title={isPlaying ? "Pause" : "Play"}
          className={clsx(
            "p-2 rounded-full transition-all",
            isPlaying
              ? "bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 border border-amber-500/40"
              : "bg-[#00e5ff]/20 text-[#00e5ff] hover:bg-[#00e5ff]/30 border border-[#00e5ff]/50 shadow-[0_0_8px_rgba(0,229,255,0.25)]"
          )}
        >
          {isPlaying ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <button
          onClick={onStop}
          title="Stop"
          className="p-1.5 rounded hover:bg-[#21262d] text-[#c9d1d9] hover:text-red-400 transition-colors"
        >
          <Square size={12} />
        </button>
      </div>

      {/* Elapsed time */}
      <span className="text-[13px] text-[#8b949e] tabular-nums w-12 text-right font-mono shrink-0">
        {formatTime(elapsed)}
      </span>

      {/* Scrubber bar — tall interactive area for easy mouse/touch dragging */}
      <div
        ref={scrubberRef}
        className="flex-1 h-8 flex items-center cursor-pointer group touch-none"
        onMouseDown={handleMouseDown}
        onTouchStart={handleTouchStart}
        role="slider"
        aria-valuenow={playbackIndex}
        aria-valuemin={0}
        aria-valuemax={total - 1}
        aria-label="Playback position"
      >
        {/* Track */}
        <div className="w-full h-2 bg-[#1c2030] rounded-full relative shadow-inner">
          {/* Buffered/loaded indicator */}
          <div className="absolute inset-y-0 left-0 right-0 rounded-full bg-[#2d3748]/60" />
          {/* Progress fill */}
          <div
            className={clsx(
              "absolute inset-y-0 left-0 rounded-full transition-none",
              isPlaying ? "bg-[#00e5ff]" : "bg-[#00b8d4]"
            )}
            style={{ width: `${thumbPct}%` }}
          />
          {/* Thumb */}
          <div
            className={clsx(
              "absolute top-1/2 -translate-y-1/2 rounded-full border-2 transition-transform duration-75 shadow-lg",
              dragging
                ? "w-5 h-5 bg-white border-[#00e5ff] shadow-[0_0_12px_rgba(0,229,255,0.6)]"
                : isPlaying
                ? "w-4 h-4 bg-[#00e5ff] border-[#007acc] group-hover:scale-125 shadow-[0_0_6px_rgba(0,229,255,0.4)]"
                : "w-4 h-4 bg-[#00b8d4] border-[#007acc] group-hover:scale-125"
            )}
            style={{ left: `clamp(0px, calc(${thumbPct}% - 8px), calc(100% - 16px))` }}
          />
        </div>
      </div>

      {/* Total time */}
      <span className="text-[13px] text-[#8b949e] tabular-nums w-12 font-mono shrink-0">
        {formatTime(duration)}
      </span>

      {/* Speed selector */}
      <div className="flex items-center gap-1 ml-1 shrink-0">
        {SPEEDS.map(s => (
          <button
            key={s}
            onClick={() => onSpeedChange(s)}
            className={clsx(
              "px-2 py-1 rounded text-[11px] font-semibold transition-all",
              speed === s
                ? "bg-[#00e5ff]/20 text-[#00e5ff] border border-[#00e5ff]/50 shadow-[0_0_6px_rgba(0,229,255,0.2)]"
                : "text-[#8b949e] hover:text-[#e6edf3] hover:bg-[#21262d] border border-transparent"
            )}
          >
            {s}x
          </button>
        ))}
      </div>
    </div>
  );
}
