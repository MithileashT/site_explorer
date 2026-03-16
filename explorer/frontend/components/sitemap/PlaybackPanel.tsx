"use client";

/**
 * PlaybackPanel
 * ─────────────
 * In-UI playback controls for ROS bag trajectory replay:
 *   - Play / Pause / Stop buttons
 *   - Speed selector (0.25x, 0.5x, 1x, 2x, 5x)
 *   - Draggable scrubber bar mapped to trajectory timestamps
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

  const seekFromEvent = useCallback(
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

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      setDragging(true);
      seekFromEvent(e.clientX);
    },
    [seekFromEvent]
  );

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => seekFromEvent(e.clientX);
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, seekFromEvent]);

  if (total < 2) return null;

  const t0 = trajectory[0].timestamp;
  const tEnd = trajectory[total - 1].timestamp;
  const duration = tEnd - t0;
  const elapsed = playbackIndex < total
    ? trajectory[playbackIndex].timestamp - t0
    : duration;
  const progress = total > 1 ? playbackIndex / (total - 1) : 0;

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-[#161b22] border-t-2 border-[#00e5ff]/20 select-none shadow-lg shadow-black/40">
      {/* Transport controls */}
      <div className="flex items-center gap-1.5">
        <button
          onClick={onStop}
          title="Stop & reset"
          className="p-1.5 rounded hover:bg-[#21262d] text-[#c9d1d9] hover:text-white transition-colors"
        >
          <SkipBack size={14} />
        </button>
        <button
          onClick={onPlayPause}
          title={isPlaying ? "Pause" : "Play"}
          className={clsx(
            "p-2 rounded-full transition-colors",
            isPlaying
              ? "bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 border border-amber-500/30"
              : "bg-[#00e5ff]/15 text-[#00e5ff] hover:bg-[#00e5ff]/25 border border-[#00e5ff]/30"
          )}
        >
          {isPlaying ? <Pause size={14} /> : <Play size={14} />}
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
      <span className="text-[13px] text-[#c9d1d9] tabular-nums w-12 text-right font-mono">
        {formatTime(elapsed)}
      </span>

      {/* Scrubber bar */}
      <div
        ref={scrubberRef}
        className="flex-1 h-6 flex items-center cursor-pointer group"
        onMouseDown={handleMouseDown}
      >
        <div className="w-full h-1.5 bg-[#2d2d3d] rounded-full relative">
          {/* Progress fill */}
          <div
            className="absolute inset-y-0 left-0 bg-[#00e5ff] rounded-full"
            style={{ width: `${progress * 100}%` }}
          />
          {/* Thumb */}
          <div
            className={clsx(
              "absolute top-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full border-2 transition-all shadow-md",
              dragging
                ? "bg-white border-[#00e5ff] scale-125 shadow-[#00e5ff]/40"
                : "bg-[#00e5ff] border-[#00b8d4] group-hover:scale-110"
            )}
            style={{ left: `calc(${progress * 100}% - 7px)` }}
          />
        </div>
      </div>

      {/* Total time */}
      <span className="text-[13px] text-[#c9d1d9] tabular-nums w-12 font-mono">
        {formatTime(duration)}
      </span>

      {/* Speed selector */}
      <div className="flex items-center gap-1 ml-1">
        {SPEEDS.map(s => (
          <button
            key={s}
            onClick={() => onSpeedChange(s)}
            className={clsx(
              "px-2 py-1 rounded text-[11px] font-semibold transition-all",
              speed === s
                ? "bg-[#00e5ff]/20 text-[#00e5ff] border border-[#00e5ff]/40"
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
