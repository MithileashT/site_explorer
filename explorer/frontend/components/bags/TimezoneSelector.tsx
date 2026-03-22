"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { Globe, ChevronDown, Check } from "lucide-react";
import { COMMON_TIMEZONES, getTimezoneOffsetMinutes } from "@/lib/timezone-utils";
import type { TimezoneOption } from "@/lib/timezone-utils";

interface Props {
  value: string;              // IANA timezone ID
  onChange: (tz: string) => void;
  systemTz?: string | null;   // auto-detected system TZ (highlighted in dropdown)
  disabled?: boolean;
}

export default function TimezoneSelector({ value, onChange, systemTz, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  // Build timezone list — ensure system TZ is always present
  const timezones = useMemo(() => {
    if (!systemTz || COMMON_TIMEZONES.some((t) => t.value === systemTz)) {
      return COMMON_TIMEZONES;
    }
    const offset = getTimezoneOffsetMinutes(systemTz);
    const systemOption: TimezoneOption = {
      value: systemTz,
      label: `${systemTz} (UTC${offset >= 0 ? "+" : ""}${String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0")}:${String(Math.abs(offset) % 60).padStart(2, "0")})`,
      offset,
    };
    // Insert in offset-sorted position
    const list = [...COMMON_TIMEZONES];
    const idx = list.findIndex((t) => t.offset > offset);
    list.splice(idx === -1 ? list.length : idx, 0, systemOption);
    return list;
  }, [systemTz]);

  const selected = timezones.find((t) => t.value === value);
  const label = selected?.label ?? value;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(!open)}
        className={`h-7 flex items-center gap-1.5 pl-2.5 pr-2 rounded-lg border text-xs font-semibold transition-colors ${
          open
            ? "bg-blue-600/15 text-blue-400 border-blue-600/30"
            : "bg-slate-800 text-slate-300 border-slate-700 hover:border-slate-600"
        } ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
      >
        <Globe size={12} />
        <span className="truncate max-w-[160px]">{label}</span>
        <ChevronDown size={12} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 right-0 w-80 max-h-64 overflow-y-auto rounded-lg border border-slate-700 bg-slate-800 shadow-xl">
          {systemTz && (
            <div className="px-3 py-1.5 text-[10px] text-slate-500 border-b border-slate-700">
              System detected: {systemTz}
            </div>
          )}
          {timezones.map((tz) => (
            <button
              key={tz.value}
              onClick={() => { onChange(tz.value); setOpen(false); }}
              className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between transition-colors ${
                tz.value === value
                  ? "bg-blue-600/15 text-blue-400"
                  : tz.value === systemTz
                  ? "bg-emerald-600/10 text-emerald-300 hover:bg-emerald-600/20"
                  : "text-slate-300 hover:bg-white/5"
              }`}
            >
              <span>{tz.label}</span>
              <span className="flex items-center gap-1.5">
                {tz.value === systemTz && (
                  <span className="text-[10px] text-emerald-500">System</span>
                )}
                {tz.value === value && <Check size={12} />}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
