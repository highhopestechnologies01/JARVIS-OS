"use client";

import useSWR from "swr";
import { useState } from "react";

interface ScheduledJob {
  id: string;
  name: string;
  next_run: string | null;
  next_run_relative: string;
  trigger: string;
}

interface JobsResponse {
  jobs: ScheduledJob[];
  count: number;
  scheduler_running: boolean;
}

const HERMES = process.env.NEXT_PUBLIC_HERMES_URL ?? "http://localhost:8001";

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function SchedulerPanel() {
  const { data, error, isLoading, mutate } = useSWR<JobsResponse>(
    `${HERMES}/api/v1/scheduler/jobs`,
    fetcher,
    { refreshInterval: 30_000 }
  );

  const [triggering, setTriggering] = useState<string | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const triggerJob = async (jobId: string) => {
    setTriggering(jobId);
    setTriggerMsg(null);
    try {
      const res = await fetch(`${HERMES}/api/v1/scheduler/trigger/${jobId}`, {
        method: "POST",
      });
      const body = await res.json();
      setTriggerMsg(`✓ ${body.job_name} triggered`);
      setTimeout(() => setTriggerMsg(null), 4000);
    } catch {
      setTriggerMsg("✗ Failed to trigger job");
      setTimeout(() => setTriggerMsg(null), 4000);
    } finally {
      setTriggering(null);
      mutate();
    }
  };

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider">
          Scheduler
        </h2>
        <span
          className={`text-xs font-mono px-2 py-0.5 rounded-full border ${
            data?.scheduler_running
              ? "text-jarvis-green border-jarvis-green/30 bg-jarvis-green/10"
              : "text-jarvis-muted border-jarvis-border"
          }`}
        >
          {data?.scheduler_running ? "● running" : "○ stopped"}
        </span>
      </div>

      {isLoading && (
        <p className="text-jarvis-muted text-sm animate-pulse">Loading jobs...</p>
      )}

      {error && (
        <p className="text-jarvis-red text-sm">Scheduler unavailable.</p>
      )}

      {!isLoading && !error && data?.jobs.length === 0 && (
        <p className="text-jarvis-muted text-sm">No jobs registered.</p>
      )}

      {data?.jobs && data.jobs.length > 0 && (
        <div className="space-y-2">
          {data.jobs.map((job) => (
            <div
              key={job.id}
              className="flex items-center justify-between py-2 border-b border-jarvis-border/50 last:border-0 gap-2"
            >
              <div className="min-w-0 flex-1">
                <div className="text-jarvis-text text-xs font-medium truncate">{job.name}</div>
                <div className="text-jarvis-muted text-xs font-mono mt-0.5 truncate">
                  next: {job.next_run_relative ?? "—"}
                </div>
              </div>
              <button
                onClick={() => triggerJob(job.id)}
                disabled={triggering === job.id}
                className="shrink-0 text-xs px-2 py-1 rounded border border-jarvis-accent/40
                  text-jarvis-accent hover:bg-jarvis-accent/10 transition-colors
                  disabled:opacity-40 disabled:cursor-not-allowed font-mono"
              >
                {triggering === job.id ? "..." : "▶ run"}
              </button>
            </div>
          ))}
        </div>
      )}

      {triggerMsg && (
        <div
          className={`mt-3 text-xs font-mono px-3 py-2 rounded border ${
            triggerMsg.startsWith("✓")
              ? "text-jarvis-green border-jarvis-green/20 bg-jarvis-green/5"
              : "text-jarvis-red border-jarvis-red/20 bg-jarvis-red/5"
          }`}
        >
          {triggerMsg}
        </div>
      )}
    </div>
  );
}
