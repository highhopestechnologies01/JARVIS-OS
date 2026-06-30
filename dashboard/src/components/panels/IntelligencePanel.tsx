"use client";

import useSWR from "swr";
import { useState } from "react";

interface Insight {
  content: string;
  created_at: string;
  importance: number;
}

interface InsightsResponse {
  insights: Insight[];
  last_analysis: string | null;
  weekly_plan: string | null;
  weekly_plan_date: string | null;
}

const HERMES = process.env.NEXT_PUBLIC_HERMES_URL ?? "http://localhost:8001";
const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function IntelligencePanel() {
  const { data, error, isLoading, mutate } = useSWR<InsightsResponse>(
    `${HERMES}/api/v1/intelligence/insights`,
    fetcher,
    { refreshInterval: 60_000 }
  );

  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeMsg, setAnalyzeMsg] = useState<string | null>(null);

  const triggerAnalysis = async () => {
    setAnalyzing(true);
    setAnalyzeMsg(null);
    try {
      await fetch(`${HERMES}/api/v1/intelligence/analyze`, { method: "POST" });
      setAnalyzeMsg("Analysis started — refreshing in 15s...");
      setTimeout(() => {
        mutate();
        setAnalyzeMsg(null);
      }, 15_000);
    } catch {
      setAnalyzeMsg("Failed to start analysis");
    } finally {
      setAnalyzing(false);
    }
  };

  const formatTime = (iso: string | null) => {
    if (!iso) return null;
    const d = new Date(iso);
    const now = new Date();
    const diff = Math.floor((now.getTime() - d.getTime()) / 60000);
    if (diff < 60) return `${diff}m ago`;
    if (diff < 1440) return `${Math.floor(diff / 60)}h ago`;
    return `${Math.floor(diff / 1440)}d ago`;
  };

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider">
            AI Intelligence
          </h2>
          {data?.last_analysis && (
            <p className="text-jarvis-muted text-xs mt-0.5">
              Last analysis: {formatTime(data.last_analysis)}
            </p>
          )}
        </div>
        <button
          onClick={triggerAnalysis}
          disabled={analyzing}
          className="text-xs px-2 py-1 rounded border border-jarvis-accent/40
            text-jarvis-accent hover:bg-jarvis-accent/10 transition-colors
            disabled:opacity-40 disabled:cursor-not-allowed font-mono shrink-0"
        >
          {analyzing ? "..." : "⚡ analyze"}
        </button>
      </div>

      {isLoading && (
        <p className="text-jarvis-muted text-sm animate-pulse">Loading insights...</p>
      )}

      {error && (
        <p className="text-jarvis-red text-sm">Intelligence module unavailable.</p>
      )}

      {/* Pattern Insights */}
      {data?.insights && data.insights.length > 0 ? (
        <div className="space-y-2">
          {data.insights.map((insight, i) => (
            <div
              key={i}
              className="flex gap-2 py-2 border-b border-jarvis-border/40 last:border-0"
            >
              <span className="text-jarvis-accent text-xs mt-0.5 shrink-0">◆</span>
              <p className="text-jarvis-text text-xs leading-relaxed">{insight.content}</p>
            </div>
          ))}
        </div>
      ) : (
        !isLoading && !error && (
          <div className="py-3 text-center">
            <p className="text-jarvis-muted text-xs">No insights yet.</p>
            <p className="text-jarvis-muted text-xs mt-1">
              Pattern analysis runs at 3am daily.
            </p>
            <button
              onClick={triggerAnalysis}
              disabled={analyzing}
              className="mt-2 text-xs text-jarvis-accent hover:underline disabled:opacity-40"
            >
              Run now →
            </button>
          </div>
        )
      )}

      {/* Weekly Plan preview */}
      {data?.weekly_plan && (
        <div className="mt-4 pt-3 border-t border-jarvis-border/50">
          <p className="text-jarvis-muted text-xs uppercase tracking-wider mb-1">
            Weekly Plan · {data.weekly_plan_date?.replace("week_of_", "") ?? ""}
          </p>
          <p className="text-jarvis-text text-xs leading-relaxed line-clamp-3">
            {data.weekly_plan}
          </p>
        </div>
      )}

      {analyzeMsg && (
        <div className="mt-3 text-xs font-mono px-3 py-2 rounded border border-jarvis-accent/20 bg-jarvis-accent/5 text-jarvis-accent">
          {analyzeMsg}
        </div>
      )}
    </div>
  );
}
