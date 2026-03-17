"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Manrope, Space_Grotesk } from "next/font/google";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Copy,
  CopyCheck,
  Link2,
  Loader2,
  MessagesSquare,
  Radar,
  ShieldAlert,
  Sparkles,
  TerminalSquare,
} from "lucide-react";

import { investigateSlackThread, listSiteMapSites, getSlackLLMStatus, getAIProviders, setAIProvider } from "@/lib/api";
import type {
  SlackThreadInvestigationRequest,
  SlackThreadInvestigationResponse,
  SlackLLMStatusResponse,
  AIProviderInfo,
} from "@/lib/types";

const headingFont = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-slack-heading",
});

const bodyFont = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-slack-body",
});

function riskPill(risk: string): string {
  if (risk === "high") {
    return "border-red-400/35 bg-red-500/15 text-red-200";
  }
  if (risk === "low") {
    return "border-emerald-400/35 bg-emerald-500/15 text-emerald-200";
  }
  return "border-amber-400/35 bg-amber-500/15 text-amber-200";
}

function CopyButton({ text, className = "" }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? "Copied!" : "Copy to clipboard"}
      className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs transition-colors ${
        copied
          ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-300"
          : "border-white/10 bg-white/[0.03] text-slate-400 hover:border-sky-400/30 hover:bg-sky-500/10 hover:text-sky-200"
      } ${className}`}
    >
      {copied ? <CopyCheck size={12} /> : <Copy size={12} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function SlackInvestigationPage() {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = useForm<SlackThreadInvestigationRequest>({
    defaultValues: {
      slack_thread_url: "",
      description: "",
      site_id: "",
      include_bots: false,
      max_messages: 200,
    },
  });

  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<SlackThreadInvestigationResponse | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [sites, setSites] = useState<Array<{ id: string; name: string }>>([]);
  const [sitesLoading, setSitesLoading] = useState(true);
  const [sitesError, setSitesError] = useState("");
  const [llmStatus, setLlmStatus] = useState<SlackLLMStatusResponse | null>(null);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [providers, setProviders] = useState<AIProviderInfo[]>([]);
  const [activeProvider, setActiveProvider] = useState<AIProviderInfo | null>(null);
  const [providerSwitching, setProviderSwitching] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadSites() {
      setSitesLoading(true);
      setSitesError("");
      try {
        const loaded = await listSiteMapSites();
        if (cancelled) return;

        const sorted = [...loaded].sort((a, b) => a.name.localeCompare(b.name));
        setSites(sorted);
      } catch (err) {
        if (cancelled) return;
        setSites([]);
        setSitesError(err instanceof Error ? err.message : "Failed to load site list.");
      } finally {
        if (!cancelled) {
          setSitesLoading(false);
        }
      }
    }

    loadSites();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Single consolidated fetch for provider info + LLM status
    getAIProviders()
      .then((resp) => {
        setProviders(resp.providers);
        setActiveProvider(resp.active);
        setSelectedModel(resp.active.id);
      })
      .catch(() => {});

    getSlackLLMStatus()
      .then((s) => {
        setLlmStatus(s);
        // Only use status for LLM readiness info, not provider selection
      })
      .catch(() => {
        // If status fails, providers endpoint already handles selection
      });
  }, []);

  async function onSubmit(data: SlackThreadInvestigationRequest) {
    setRunning(true);
    setError("");
    setResult(null);
    try {
      // If a provider is selected and it differs from active, switch globally first
      if (selectedModel && activeProvider && selectedModel !== activeProvider.id) {
        try {
          const resp = await setAIProvider(selectedModel);
          setActiveProvider(resp.active);
          setProviders(resp.providers);
        } catch {
          // Non-fatal: proceed with current active provider
        }
      }

      const payload: SlackThreadInvestigationRequest = {
        ...data,
        site_id: data.site_id?.trim() || undefined,
        max_messages: data.max_messages || 200,
        model_override: selectedModel || undefined,
      };
      const response = await investigateSlackThread(payload);
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to investigate Slack thread.");
    } finally {
      setRunning(false);
    }
  }

  function resetAll() {
    reset();
    setResult(null);
    setError("");
    setShowRaw(false);
  }

  return (
    <div className={`${headingFont.variable} ${bodyFont.variable} relative mx-auto max-w-[1400px] px-4 pb-20 pt-6 lg:px-8`}>
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-20 top-0 h-80 w-80 rounded-full bg-sky-400/15 blur-3xl" />
        <div className="absolute right-2 top-16 h-80 w-80 rounded-full bg-emerald-400/10 blur-3xl" />
      </div>

      <section className="mb-6 overflow-hidden rounded-2xl border border-sky-400/20 bg-gradient-to-r from-[#0a2536]/95 via-[#122338]/95 to-[#1c2238]/95 p-5 shadow-[0_20px_50px_rgba(10,30,45,0.45)]">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="rounded-xl border border-sky-300/30 bg-sky-300/10 p-2.5">
              <MessagesSquare size={20} className="text-sky-200" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-slate-100 [font-family:var(--font-slack-heading)]">
                Slack Investigation
              </h1>
              <p className="mt-1 text-sm text-slate-300 [font-family:var(--font-slack-body)]">
                Fetch a Slack thread, summarize operational context, and convert discussion into actionable investigation signals.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 lg:min-w-[260px]">
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-slate-400">State</p>
              <p className="text-sm font-semibold text-slate-100">{running ? "Running" : result ? "Completed" : "Idle"}</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-slate-400">Messages</p>
              <p className="text-sm font-semibold text-slate-100">{result?.message_count ?? "-"}</p>
            </div>
          </div>
        </div>
      </section>

      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(340px,0.8fr)_minmax(0,1.2fr)]">
          <div className="space-y-4 xl:sticky xl:top-6">
            <section className="rounded-2xl border border-sky-500/20 bg-slate-900/85 p-5">
              <h2 className="text-sm font-semibold text-slate-100 [font-family:var(--font-slack-heading)]">Thread Details</h2>
              <p className="mt-1 text-xs text-slate-400">Provide Slack thread link and investigation context.</p>

              <div className="mt-4 space-y-4">
                <div>
                  <label className="mb-1 block text-xs text-slate-300">Slack thread URL *</label>
                  <div className="relative">
                    <Link2 size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                    <input
                      className={`input pl-9 ${errors.slack_thread_url ? "border-red-400" : ""}`}
                      placeholder="https://workspace.slack.com/archives/C123/p1772691175223000"
                      {...register("slack_thread_url", { required: true, minLength: 15 })}
                    />
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-xs text-slate-300">Description *</label>
                  <textarea
                    rows={5}
                    className={`input resize-none ${errors.description ? "border-red-400" : ""}`}
                    placeholder="Describe what you want to extract from this Slack thread (incident pattern, root cause clues, action items)."
                    {...register("description", { required: true, minLength: 10 })}
                  />
                </div>

                <div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-300">Site ID</label>
                    <div className="relative">
                      <select
                        className="input appearance-none pr-10"
                        disabled={sitesLoading || running}
                        {...register("site_id")}
                      >
                        <option value="">
                          {sitesLoading
                            ? "Loading sites..."
                            : sites.length > 0
                              ? "Select a site (optional)"
                              : "No sites available"}
                        </option>
                        {sites.map((site) => (
                          <option key={site.id} value={site.id}>
                            {site.name} ({site.id})
                          </option>
                        ))}
                      </select>
                      <ChevronDown
                        size={14}
                        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-500"
                      />
                    </div>
                    {sitesError && (
                      <p className="mt-1 text-xs text-amber-200">Unable to refresh sites: {sitesError}</p>
                    )}
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs text-slate-300">Max messages</label>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      className="input"
                      {...register("max_messages", { valueAsNumber: true, min: 1, max: 500 })}
                    />
                  </div>

                  <label className="mt-6 flex items-center gap-2 rounded-xl border border-white/10 bg-slate-950/30 px-3 py-2 text-sm text-slate-200">
                    <input type="checkbox" className="rounded border-slate-600 bg-slate-800" {...register("include_bots")} />
                    Include bot messages
                  </label>
                </div>

                <div>
                  <label className="mb-1 block text-xs text-slate-300">AI Provider / Model</label>
                  <div className="relative">
                    <select
                      className="input appearance-none pr-10"
                      value={selectedModel}
                      onChange={async (e) => {
                        const newId = e.target.value;
                        setSelectedModel(newId);
                        // Switch provider globally
                        if (newId && newId !== activeProvider?.id) {
                          setProviderSwitching(true);
                          try {
                            const resp = await setAIProvider(newId);
                            setActiveProvider(resp.active);
                            setProviders(resp.providers);
                          } catch {
                            // Revert selection on failure
                            if (activeProvider) setSelectedModel(activeProvider.id);
                          } finally {
                            setProviderSwitching(false);
                          }
                        }
                      }}
                      disabled={running || providerSwitching || (providers.length === 0 && !llmStatus)}
                    >
                      {providers.length === 0 && !llmStatus && (
                        <option value="">Loading models...</option>
                      )}
                      {providers.length === 0 && llmStatus && llmStatus.installed.length === 0 && (
                        <option value="">No models available</option>
                      )}
                      {providers.length > 0 ? (
                        <>
                          {/* Group: Ollama models */}
                          <optgroup label="Local Models (Ollama)">
                            {providers
                              .filter((p) => p.type === "ollama")
                              .map((p) => (
                                <option key={p.id} value={p.id}>
                                  {p.name}
                                  {activeProvider?.id === p.id ? " (active)" : ""}
                                </option>
                              ))}
                          </optgroup>
                          {/* Group: OpenAI models */}
                          {providers.some((p) => p.type === "openai") && (
                            <optgroup label="OpenAI (Custom API Key)">
                              {providers
                                .filter((p) => p.type === "openai")
                                .map((p) => (
                                  <option key={p.id} value={p.id}>
                                    {p.name}
                                    {activeProvider?.id === p.id ? " (active)" : ""}
                                  </option>
                                ))}
                            </optgroup>
                          )}
                        </>
                      ) : (
                        /* Fallback: show installed Ollama models from status */
                        llmStatus && llmStatus.installed.map((m) => (
                          <option key={m} value={m}>
                            {m}
                            {m === llmStatus.text_model ? " (default)" : ""}
                          </option>
                        ))
                      )}
                    </select>
                    <ChevronDown
                      size={14}
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-500"
                    />
                  </div>
                  {providerSwitching && (
                    <p className="mt-0.5 text-[10px] text-sky-400">Switching provider...</p>
                  )}
                  {!providerSwitching && activeProvider && (
                    <p className="mt-0.5 text-[10px] text-slate-600">
                      Active: {activeProvider.name} ({activeProvider.type})
                      {providers.length > 0 && ` · ${providers.length} available`}
                    </p>
                  )}
                  {!providerSwitching && !activeProvider && llmStatus && (
                    <p className="mt-0.5 text-[10px] text-slate-600">
                      {llmStatus.installed.length} model{llmStatus.installed.length !== 1 ? "s" : ""} installed
                    </p>
                  )}
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-emerald-500/20 bg-slate-900/85 p-5">
              <h3 className="text-sm font-semibold text-slate-100 [font-family:var(--font-slack-heading)]">Actions</h3>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <button type="submit" className="btn btn-primary justify-center py-2.5" disabled={running}>
                  {running ? <><Loader2 size={15} className="animate-spin" /> Investigating...</> : <><Radar size={15} /> Investigate Thread</>}
                </button>
                <button type="button" className="btn btn-ghost justify-center py-2.5" onClick={resetAll} disabled={running}>
                  Reset
                </button>
              </div>
            </section>

            {isDirty && !running && (
              <div className="rounded-xl border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-xs text-amber-100">
                Unsaved input detected. Run investigation to refresh insights.
              </div>
            )}
          </div>

          <div className="space-y-4">
            {error && (
              <div className="rounded-2xl border border-red-700/40 bg-red-950/25 p-4 text-sm text-red-200">
                <div className="flex items-start gap-2">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  <p>{error}</p>
                </div>
              </div>
            )}

            {!result && !running && !error && (
              <section className="flex h-[340px] flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-slate-600/80 bg-gradient-to-b from-slate-900/90 to-slate-900/55 p-6 text-center">
                <div className="rounded-2xl border border-sky-500/25 bg-sky-500/10 p-3">
                  <Sparkles size={28} className="text-sky-200" />
                </div>
                <div>
                  <p className="text-base font-semibold text-slate-100 [font-family:var(--font-slack-heading)]">
                    Ready for Slack thread investigation
                  </p>
                  <p className="mt-1 text-sm text-slate-400">
                    Submit a Slack thread URL and context to generate structured findings and recommendations.
                  </p>
                </div>
              </section>
            )}

            {running && (
              <section className="rounded-2xl border border-sky-500/25 bg-sky-950/20 p-4 text-sky-200">
                <div className="flex items-center gap-2 text-sm">
                  <Loader2 size={14} className="animate-spin" />
                  Fetching Slack thread and generating summary...
                </div>
              </section>
            )}

            {result && (
              <div className="space-y-4">
                <section className="rounded-2xl border border-slate-700/55 bg-slate-900/80 p-5">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span className={`rounded-full border px-2.5 py-1 text-xs uppercase tracking-[0.14em] ${riskPill(result.risk_level)}`}>
                      Risk: {result.risk_level}
                    </span>
                    <span className="rounded-full border border-white/15 bg-white/[0.04] px-2.5 py-1 text-xs text-slate-200">
                      Channel: {result.channel_id}
                    </span>
                    <span className="rounded-full border border-white/15 bg-white/[0.04] px-2.5 py-1 text-xs text-slate-200">
                      Participants: {result.participants.length}
                    </span>
                    {result.model_used && (
                      <span className="rounded-full border border-sky-400/25 bg-sky-500/10 px-2.5 py-1 text-xs text-sky-200">
                        Model: {result.model_used}
                      </span>
                    )}
                    {(result.actual_total_tokens ?? 0) > 0 && (() => {
                      const pin  = result.actual_prompt_tokens     ?? 0;
                      const pout = result.actual_completion_tokens ?? 0;
                      const cost = result.cost_usd ?? (pin * 2.00 + pout * 8.00) / 1_000_000;
                      return (
                        <span
                          className="rounded-full border border-emerald-400/25 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-200"
                          title={`Actual tokens used · in=${pin.toLocaleString()} out=${pout.toLocaleString()} · gpt-4.1: $2/M in, $8/M out`}
                        >
                          {pin.toLocaleString()} in | {pout.toLocaleString()} out · ${cost.toFixed(4)}
                        </span>
                      );
                    })()}
                  </div>
                </section>

                <section className="rounded-2xl border border-slate-700/55 bg-slate-900/80 p-5">
                  {/* Single copy for all three sub-sections */}
                  <div className="mb-4 flex items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold text-slate-100 [font-family:var(--font-slack-heading)]">Analysis</h2>
                    <CopyButton
                      text={[
                        "## Thread Summary",
                        result.thread_summary,
                        "",
                        "## Key Findings",
                        result.key_findings.length > 0
                          ? result.key_findings.map((f, i) => `${i + 1}. ${f}`).join("\n")
                          : "No findings generated.",
                        "",
                        "## Recommended Actions",
                        result.recommended_actions.length > 0
                          ? result.recommended_actions.map((a, i) => `${i + 1}. ${a}`).join("\n")
                          : "No actions generated.",
                      ].join("\n")}
                    />
                  </div>

                  <div className="space-y-5">
                    {/* Thread Summary */}
                    <div>
                      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400 [font-family:var(--font-slack-heading)]">
                        Thread Summary
                      </h3>
                      <div className="space-y-3 text-sm text-slate-300">
                        {result.thread_summary.split("\n\n").map((block, bi) => {
                          const boldMatch = block.match(/^\*\*(.+?)\*\*\n?([\s\S]*)$/);
                          if (boldMatch) {
                            const heading = boldMatch[1];
                            const body = boldMatch[2].trim();
                            const bullets = body.split("\n").filter((l) => l.trim().startsWith("-"));
                            return (
                              <div key={bi}>
                                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                                  {heading}
                                </p>
                                {bullets.length > 0 ? (
                                  <ul className="space-y-1 pl-1">
                                    {bullets.map((b, idx) => (
                                      <li key={idx} className="flex items-start gap-2">
                                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-sky-400/60" />
                                        <span>{b.replace(/^-\s*/, "")}</span>
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <p>{body}</p>
                                )}
                              </div>
                            );
                          }
                          return <p key={bi} className="whitespace-pre-wrap">{block}</p>;
                        })}
                      </div>
                    </div>

                    <div className="border-t border-slate-700/50" />

                    {/* Key Findings */}
                    <div>
                      <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400 [font-family:var(--font-slack-heading)]">
                        Key Findings
                      </h3>
                      {result.key_findings.length === 0 ? (
                        <p className="text-sm text-slate-500">No findings generated.</p>
                      ) : (
                        <ul className="space-y-2">
                          {result.key_findings.map((item, idx) => (
                            <li key={idx} className="flex items-start gap-2 text-sm text-slate-300">
                              <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-300" />
                              <span>{item}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="border-t border-slate-700/50" />

                    {/* Recommended Actions */}
                    <div>
                      <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400 [font-family:var(--font-slack-heading)]">
                        Recommended Actions
                      </h3>
                      {result.recommended_actions.length === 0 ? (
                        <p className="text-sm text-slate-500">No actions generated.</p>
                      ) : (
                        <ul className="space-y-2">
                          {result.recommended_actions.map((item, idx) => (
                            <li key={idx} className="flex items-start gap-2 text-sm text-slate-300">
                              <ShieldAlert size={14} className="mt-0.5 shrink-0 text-amber-300" />
                              <span>{item}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                </section>

                <section className="rounded-2xl border border-slate-700/55 bg-slate-900/80 p-5">
                  <h3 className="mb-3 text-sm font-semibold text-slate-100 [font-family:var(--font-slack-heading)]">Thread Timeline</h3>
                  {result.timeline.length === 0 ? (
                    <p className="text-sm text-slate-500">No messages were returned from Slack API.</p>
                  ) : (
                    <div className="max-h-[360px] overflow-y-auto rounded-xl border border-white/10">
                      <table className="w-full text-left text-sm">
                        <thead className="sticky top-0 bg-slate-900">
                          <tr className="border-b border-slate-700/70 text-xs uppercase tracking-wide text-slate-400">
                            <th className="px-3 py-2">Time</th>
                            <th className="px-3 py-2">User</th>
                            <th className="px-3 py-2">Message</th>
                          </tr>
                        </thead>
                        <tbody>
                          {result.timeline.map((entry, idx) => (
                            <tr key={`${entry.ts}-${idx}`} className="border-b border-slate-800/70 align-top">
                              <td className="px-3 py-2 text-xs text-slate-400">{entry.datetime || entry.ts}</td>
                              <td className="px-3 py-2 text-xs text-slate-300">{entry.user}</td>
                              <td className="px-3 py-2 text-xs text-slate-200">{entry.text}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>

                <section className="rounded-2xl border border-slate-700/55 bg-slate-900/80 p-5">
                  <button
                    type="button"
                    className="btn btn-ghost mb-3"
                    onClick={() => setShowRaw((prev) => !prev)}
                  >
                    <TerminalSquare size={14} /> {showRaw ? "Hide" : "Show"} Raw Analysis
                  </button>
                  {showRaw && (
                    <pre className="max-h-[300px] overflow-y-auto rounded-xl border border-white/10 bg-slate-950/60 p-3 text-xs text-slate-300">
                      {result.raw_analysis || "No raw model output returned."}
                    </pre>
                  )}
                </section>
              </div>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
