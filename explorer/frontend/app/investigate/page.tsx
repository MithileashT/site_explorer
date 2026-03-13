"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { streamInvestigation } from "@/lib/api";
import type {
  IncidentImpact,
  InvestigationFormInput,
  OrchestratorResponse,
  SSEEvent,
} from "@/lib/types";
import ConfidenceGauge from "@/components/investigation/ConfidenceGauge";
import RankedCausesPanel from "@/components/investigation/RankedCausesPanel";
import SimilarCasesTable from "@/components/investigation/SimilarCasesTable";
import HumanInterventionBanner from "@/components/investigation/HumanInterventionBanner";
import ReactMarkdown from "react-markdown";
import { Manrope, Space_Grotesk } from "next/font/google";
import {
  AlertTriangle,
  CalendarClock,
  Circle,
  Clock3,
  Gauge,
  Link2,
  SearchCode,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronRight,
  Play,
  Sparkles,
} from "lucide-react";

const headingFont = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-investigate-heading",
});

const bodyFont = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-investigate-body",
});

type StepStatus = "pending" | "running" | "done" | "error";

interface Step {
  id: string;
  label: string;
  status: StepStatus;
  message: string;
}

const STEP_LABELS = {
  start: "Initialising",
  bag_analysis: "Analysing telemetry",
  similarity_search: "Searching past incidents",
  llm_analysis: "Running AI analysis",
  complete: "Complete",
} as const;

const IMPACT_OPTIONS: Array<{ value: IncidentImpact; label: string; hint: string }> = [
  { value: "mission_blocked", label: "Mission blocked", hint: "Operations fully interrupted" },
  { value: "degraded", label: "Degraded", hint: "Running below expected performance" },
  { value: "intermittent", label: "Intermittent", hint: "Issue appears and disappears" },
  { value: "unknown", label: "Unknown", hint: "Impact still being assessed" },
];

function impactDisplayLabel(impact: IncidentImpact): string {
  const found = IMPACT_OPTIONS.find((item) => item.value === impact);
  return found ? found.label : "Unknown";
}

function buildIncidentTitle(summary: string, impact: IncidentImpact, detectedAt?: string): string {
  const cleanedSummary = summary.replace(/\s+/g, " ").trim();
  const summarySnippet = cleanedSummary.split(".", 1)[0].slice(0, 64).trim();
  const base = summarySnippet || "Incident investigation";
  const impactPrefix = impactDisplayLabel(impact);
  const timeSuffix = detectedAt ? ` @ ${new Date(detectedAt).toLocaleString()}` : "";
  return `${impactPrefix}: ${base}${timeSuffix}`.slice(0, 120);
}

function buildInvestigationDescription(data: InvestigationFormInput): string {
  const context: string[] = [
    `Observed impact: ${impactDisplayLabel(data.observed_impact)}`,
    `Detected at: ${data.detected_at ? new Date(data.detected_at).toLocaleString() : "Not provided"}`,
    `Grafana: ${data.grafana_link?.trim() || "Not provided"}`,
    `Config changed recently: ${data.config_changed ? "Yes" : "No"}`,
  ];
  return `${data.incident_summary.trim()}\n\n${context.join("\n")}`;
}

function StepRow({ step }: { step: Step }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-950/45 px-3 py-2.5">
      <div className="flex items-center gap-2.5 text-sm">
        {step.status === "running" && <Loader2 size={14} className="animate-spin text-cyan-300 shrink-0" />}
        {step.status === "done" && <CheckCircle2 size={14} className="text-emerald-300 shrink-0" />}
        {step.status === "error" && <XCircle size={14} className="text-red-400 shrink-0" />}
        {step.status === "pending" && <Circle size={14} className="text-slate-600 shrink-0" />}
        <span
          className={
            step.status === "running"
              ? "text-cyan-200"
              : step.status === "done"
                ? "text-emerald-200"
                : step.status === "error"
                  ? "text-red-300"
                  : "text-slate-400"
          }
        >
          {step.label}
        </span>
        <span
          className={
            "ml-auto rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider " +
            (step.status === "running"
              ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-300"
              : step.status === "done"
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : step.status === "error"
                  ? "border-red-500/40 bg-red-500/10 text-red-300"
                  : "border-slate-700/70 bg-slate-800/70 text-slate-500")
          }
        >
          {step.status}
        </span>
      </div>
      {step.message && step.status === "running" && (
        <p className="mt-1 truncate text-xs text-slate-500">{step.message}</p>
      )}
    </div>
  );
}

export default function InvestigatePage() {
  const {
    register,
    handleSubmit,
    setValue,
    reset,
    watch,
    formState: { errors, isDirty },
  } = useForm<InvestigationFormInput>({
    defaultValues: {
      incident_summary: "",
      observed_impact: "unknown",
      detected_at: "",
      grafana_link: "",
      config_changed: false,
    },
  });

  const [steps, setSteps] = useState<Step[]>([]);
  const [result, setResult] = useState<OrchestratorResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [errMsg, setErrMsg] = useState("");
  const [tab, setTab] = useState<"causes" | "solutions" | "similar" | "raw">("causes");

  const selectedImpact = watch("observed_impact") ?? "unknown";
  const completedSteps = steps.filter((s) => s.status === "done").length;
  const currentStep = steps.find((s) => s.status === "running");
  const progressPct = steps.length > 0 ? Math.round((completedSteps / steps.length) * 100) : 0;

  const stateLabel = running ? "Running" : errMsg ? "Failed" : result ? "Completed" : "Idle";

  function resetAll() {
    reset({
      incident_summary: "",
      observed_impact: "unknown",
      detected_at: "",
      grafana_link: "",
      config_changed: false,
    });
    setSteps([]);
    setResult(null);
    setErrMsg("");
  }

  function onSubmit(data: InvestigationFormInput) {
    setResult(null);
    setErrMsg("");
    setRunning(true);

    const initial: Step[] = Object.keys(STEP_LABELS).map((id) => ({
      id,
      label: STEP_LABELS[id as keyof typeof STEP_LABELS],
      status: "pending",
      message: "",
    }));
    setSteps(initial);

    const title = buildIncidentTitle(data.incident_summary, data.observed_impact, data.detected_at);
    const description = buildInvestigationDescription(data);

    const unsub = streamInvestigation(
      { title, description },
      (ev: SSEEvent) => {
        setSteps((prev) =>
          prev.map((s) => {
            if (s.id === ev.step) {
              return { ...s, status: "running", message: ev.message };
            }
            const prevIdx = Object.keys(STEP_LABELS).indexOf(s.id);
            const curIdx = Object.keys(STEP_LABELS).indexOf(ev.step);
            if (prevIdx < curIdx && s.status === "running") {
              return { ...s, status: "done" };
            }
            return s;
          }),
        );

        if (ev.step === "complete" && ev.data) {
          setResult(ev.data);
          setSteps((prev) => prev.map((s) => ({ ...s, status: "done" })));
          setRunning(false);
          unsub();
        }

        if (ev.step === "error") {
          setErrMsg(ev.error ?? ev.message ?? "Unknown error from server.");
          setRunning(false);
          unsub();
        }
      },
      () => {
        setErrMsg("Connection to server lost. Please retry.");
        setRunning(false);
      },
    );
  }

  return (
    <div
      className={`${headingFont.variable} ${bodyFont.variable} relative mx-auto max-w-[1400px] px-4 pb-24 pt-6 lg:px-8 lg:pb-10`}
    >
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-24 top-2 h-80 w-80 rounded-full bg-cyan-400/15 blur-3xl" />
        <div className="absolute right-8 top-16 h-[22rem] w-[22rem] rounded-full bg-amber-400/10 blur-3xl" />
        <div className="absolute bottom-8 left-1/3 h-44 w-96 rounded-full bg-emerald-500/10 blur-3xl" />
      </div>

      <div className="relative mb-6 overflow-hidden rounded-2xl border border-cyan-400/25 bg-gradient-to-r from-[#0b1f2f]/95 via-[#10243a]/95 to-[#1b2638]/95 p-5 shadow-[0_20px_50px_rgba(9,27,45,0.45)]">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 rounded-xl border border-cyan-300/35 bg-cyan-300/10 p-2.5">
              <Sparkles size={18} className="text-cyan-200" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">
                Incident Investigation Workspace
              </h1>
              <p className="mt-1 text-sm text-slate-300/95 [font-family:var(--font-investigate-body)]">
                Capture operational context, track pipeline execution, and review ranked outcomes in one focused triage flow.
              </p>
              {currentStep && running && (
                <p className="mt-2 text-xs text-cyan-200 [font-family:var(--font-investigate-body)]">
                  Running: {currentStep.label}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:min-w-[540px]">
            <div className="rounded-xl border border-white/15 bg-white/5 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400">State</p>
              <p className="mt-0.5 text-sm font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">{stateLabel}</p>
            </div>
            <div className="rounded-xl border border-white/15 bg-white/5 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400">Pipeline</p>
              <p className="mt-0.5 text-sm font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">
                {completedSteps}/{steps.length || 5}
              </p>
            </div>
            <div className="rounded-xl border border-white/15 bg-white/5 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400">Progress</p>
              <p className="mt-0.5 text-sm font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">{progressPct}%</p>
            </div>
            <div className="rounded-xl border border-white/15 bg-white/5 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400">Impact</p>
              <p className="mt-0.5 text-sm font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">
                {impactDisplayLabel(selectedImpact)}
              </p>
            </div>
          </div>
        </div>
      </div>

      <form onSubmit={handleSubmit(onSubmit)}>
        <input type="hidden" {...register("observed_impact", { required: true })} />

        <div className="grid items-start gap-6 xl:grid-cols-[minmax(340px,0.74fr)_minmax(0,1.26fr)]">
          <div className="space-y-4 xl:sticky xl:top-6">
            <section className="rounded-2xl border border-cyan-500/20 bg-slate-900/85 p-5 shadow-[0_14px_42px_rgba(4,15,31,0.35)]">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">Incident Details</h2>
                  <p className="text-xs text-slate-400 [font-family:var(--font-investigate-body)]">Capture what happened and impact severity.</p>
                </div>
                <span className="rounded-full border border-cyan-400/35 bg-cyan-400/10 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-cyan-200">
                  Required
                </span>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-xs text-slate-300">What happened? *</label>
                  <textarea
                    rows={5}
                    className={`input resize-none bg-slate-950/60 ${errors.incident_summary ? "border-red-400" : ""}`}
                    placeholder="Describe the incident, symptoms, and immediate behavior observed by operators."
                    {...register("incident_summary", { required: true, minLength: 20 })}
                  />
                  {errors.incident_summary && (
                    <p className="mt-1 text-xs text-red-300">Provide at least 20 characters for a useful investigation.</p>
                  )}
                </div>

                <div>
                  <label className="mb-2 block text-xs text-slate-300">Observed impact *</label>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {IMPACT_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setValue("observed_impact", option.value, { shouldDirty: true, shouldValidate: true })}
                        className={`rounded-xl border px-3 py-2 text-left transition-colors ${
                          selectedImpact === option.value
                            ? "border-amber-300/50 bg-amber-300/10 text-amber-100"
                            : "border-white/10 bg-slate-950/30 text-slate-300 hover:border-white/30"
                        }`}
                      >
                        <p className="text-sm font-medium [font-family:var(--font-investigate-heading)]">{option.label}</p>
                        <p className="mt-0.5 text-[11px] text-slate-400">{option.hint}</p>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-xs text-slate-300">When detected</label>
                  <div className="relative">
                    <CalendarClock
                      size={14}
                      className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
                    />
                    <input type="datetime-local" className="input bg-slate-950/60 pl-9" {...register("detected_at")} />
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-emerald-500/20 bg-slate-900/85 p-5 shadow-[0_14px_42px_rgba(4,15,31,0.35)]">
              <h3 className="text-sm font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">Operational Context</h3>
              <p className="mt-1 text-xs text-slate-400 [font-family:var(--font-investigate-body)]">
                Optional context enriches AI analysis without cluttering core incident details.
              </p>

              <div className="mt-4 space-y-4">
                <div>
                  <label className="mb-1 block text-xs text-slate-300">Grafana link</label>
                  <div className="relative">
                    <Link2 size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                    <input
                      className="input bg-slate-950/60 pl-9"
                      placeholder="https://grafana.example.com/d/..."
                      {...register("grafana_link")}
                    />
                  </div>
                </div>

                <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-white/10 bg-slate-950/30 px-3 py-2 text-sm text-slate-200">
                  <input type="checkbox" className="rounded border-slate-600 bg-slate-800" {...register("config_changed")} />
                  Config / firmware changed recently
                </label>
              </div>
            </section>

            <section className="rounded-2xl border border-amber-400/20 bg-slate-900/85 p-5 shadow-[0_14px_42px_rgba(4,15,31,0.35)]">
              <h3 className="text-sm font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">Run Controls</h3>
              <p className="mt-1 text-xs text-slate-400">Start a new run or reset the current workspace state.</p>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <button type="submit" className="btn btn-primary justify-center py-2.5" disabled={running}>
                  {running ? (
                    <>
                      <Loader2 size={15} className="animate-spin" /> Investigating...
                    </>
                  ) : (
                    <>
                      <Play size={15} /> Run Investigation
                    </>
                  )}
                </button>
                <button type="button" className="btn btn-ghost justify-center py-2.5" onClick={resetAll} disabled={running}>
                  Reset
                </button>
              </div>
            </section>

            {(isDirty || running) && (
              <div className="fixed bottom-4 left-4 right-4 z-20 rounded-xl border border-cyan-300/35 bg-slate-900/95 p-3 shadow-2xl lg:hidden">
                <button type="submit" className="btn btn-primary w-full justify-center py-2.5" disabled={running}>
                  {running ? (
                    <>
                      <Loader2 size={15} className="animate-spin" /> Investigation running...
                    </>
                  ) : (
                    <>
                      <Play size={15} /> Run Investigation
                    </>
                  )}
                </button>
              </div>
            )}
          </div>

          <div className="space-y-4">
            {steps.length > 0 && (
              <section className="rounded-2xl border border-slate-700/50 bg-slate-900/75 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Clock3 size={14} className="text-cyan-300" />
                    <h2 className="text-sm font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">Pipeline Timeline</h2>
                  </div>
                  <span className="text-xs text-slate-300">{progressPct}%</span>
                </div>

                <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full bg-gradient-to-r from-cyan-400 via-emerald-400 to-amber-300 transition-all duration-300"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>

                <div className="space-y-2">
                  {steps.map((s) => (
                    <StepRow key={s.id} step={s} />
                  ))}
                </div>
              </section>
            )}

            {errMsg && (
              <div className="rounded-2xl border border-red-700/40 bg-red-950/25 p-4 text-sm text-red-200">
                <div className="flex items-start gap-2">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  <p>{errMsg}</p>
                </div>
              </div>
            )}

            {result && (
              <div className="space-y-4 animate-fade-in">
                <section className="rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-emerald-950/30 to-slate-900/80 p-5">
                  <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
                    <ConfidenceGauge score={result.confidence_score} />
                    <div className="flex-1">
                      <div className="mb-2 inline-flex items-center gap-1 rounded-full border border-emerald-300/30 bg-emerald-300/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.16em] text-emerald-200">
                        <Gauge size={12} /> Findings Overview
                      </div>
                      <p className="text-2xl font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">
                        {(result.confidence_score * 100).toFixed(0)}% confidence
                      </p>
                      <p className="mt-1 text-sm text-slate-300">
                        {result.human_intervention_required
                          ? "Manual intervention is recommended before autonomous action."
                          : "Confidence is within automatic resolution range."}
                      </p>
                    </div>
                  </div>
                </section>

                <HumanInterventionBanner required={result.human_intervention_required} confidence={result.confidence_score} />

                <section className="rounded-2xl border border-slate-700/50 bg-slate-900/75 p-4">
                  <div className="mb-3 flex flex-wrap gap-1.5 border-b border-slate-700/60 pb-2">
                    {([
                      { id: "causes", label: "Root Causes" },
                      { id: "solutions", label: "Solutions" },
                      { id: "similar", label: "Similar Cases" },
                      { id: "raw", label: "Raw Analysis" },
                    ] as const).map(({ id, label }) => (
                      <button
                        key={id}
                        onClick={() => setTab(id)}
                        type="button"
                        className={`rounded-md border px-3 py-1.5 text-xs transition-colors ${
                          tab === id
                            ? "border-cyan-400/40 bg-cyan-500/15 text-cyan-200"
                            : "border-transparent text-slate-400 hover:border-white/15 hover:bg-white/[0.04] hover:text-slate-200"
                        }`}
                      >
                        {label}
                        {id === "similar" && result.similar_cases.length > 0 && (
                          <span className="badge badge-blue ml-1 px-1 py-0 text-[10px]">{result.similar_cases.length}</span>
                        )}
                      </button>
                    ))}
                  </div>

                  <div className="min-h-[330px]">
                    {tab === "causes" && (
                      <RankedCausesPanel items={result.ranked_causes} title="Ranked Root Causes" accentColour="#ef4444" />
                    )}
                    {tab === "solutions" && (
                      <RankedCausesPanel
                        items={result.ranked_solutions}
                        title="Recommended Solutions"
                        accentColour="#22c55e"
                      />
                    )}
                    {tab === "similar" && (
                      <div>
                        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Similar Past Incidents</h3>
                        <SimilarCasesTable cases={result.similar_cases} />
                      </div>
                    )}
                    {tab === "raw" && (
                      <div className="prose-dark max-h-[420px] overflow-y-auto">
                        <ReactMarkdown>{result.raw_analysis}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                </section>
              </div>
            )}

            {!result && !running && steps.length === 0 && (
              <div className="flex h-[360px] flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-slate-600/80 bg-gradient-to-b from-slate-900/90 to-slate-900/50 p-6 text-center">
                <div className="rounded-2xl border border-cyan-500/25 bg-cyan-500/10 p-3">
                  <SearchCode size={30} className="text-cyan-300" />
                </div>
                <div>
                  <p className="text-base font-semibold text-slate-100 [font-family:var(--font-investigate-heading)]">
                    Ready to investigate an incident
                  </p>
                  <p className="mt-1 text-sm text-slate-400 [font-family:var(--font-investigate-body)]">
                    Provide a high-quality incident narrative and run the pipeline to generate ranked root causes and resolution guidance.
                  </p>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <ChevronRight size={12} /> Powered by historical vector search plus LLM analysis
                </div>
              </div>
            )}

            {running && !result && (
              <div className="rounded-2xl border border-cyan-500/20 bg-cyan-950/15 p-4">
                <div className="flex items-center gap-2 text-sm text-cyan-200">
                  <Loader2 size={14} className="animate-spin" />
                  Investigation pipeline is running. Findings will appear here when complete.
                </div>
              </div>
            )}
          </div>
        </div>
      </form>

      <div className="pointer-events-none fixed bottom-3 left-1/2 hidden -translate-x-1/2 items-center gap-1 rounded-full border border-white/10 bg-slate-900/80 px-3 py-1 text-[11px] text-slate-400 backdrop-blur lg:flex">
        <Sparkles size={11} className="text-amber-300" />
        <span>Impact-aware incident workflow</span>
      </div>
    </div>
  );
}
