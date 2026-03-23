"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[AMR Platform] Unhandled error:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 p-8 text-center">
      <div className="rounded-full bg-red-500/10 p-4">
        <AlertTriangle className="h-8 w-8 text-red-400" />
      </div>
      <div>
        <h2 className="text-lg font-semibold text-slate-100">Something went wrong</h2>
        <p className="mt-1 max-w-md text-sm text-slate-400">
          {error.message || "An unexpected error occurred. Please try again."}
        </p>
      </div>
      <button
        onClick={reset}
        className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500"
      >
        <RefreshCw className="h-4 w-4" />
        Try again
      </button>
    </div>
  );
}
