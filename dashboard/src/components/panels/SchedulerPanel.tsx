import { hermesApi } from "@/lib/api";
import { format } from "date-fns";

interface ScheduledJob {
  id: string;
  name: string;
  next_run: string | null;
}

export async function SchedulerPanel() {
  let jobs: ScheduledJob[] = [];
  let error = false;

  try {
    jobs = await hermesApi<ScheduledJob[]>("/api/v1/tasks/scheduler");
  } catch {
    error = true;
  }

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider mb-4">
        Scheduler
      </h2>

      {error ? (
        <p className="text-jarvis-muted text-sm">Scheduler unavailable.</p>
      ) : jobs.length === 0 ? (
        <p className="text-jarvis-muted text-sm">No jobs registered.</p>
      ) : (
        <div className="space-y-2">
          {jobs.map((job) => (
            <div
              key={job.id}
              className="flex items-start justify-between py-2 border-b border-jarvis-border/50 last:border-0"
            >
              <div>
                <div className="text-jarvis-text text-xs font-medium">{job.name}</div>
                <div className="text-jarvis-muted text-xs font-mono mt-0.5">{job.id}</div>
              </div>
              <div className="text-jarvis-muted text-xs font-mono text-right shrink-0 ml-2">
                {job.next_run
                  ? format(new Date(job.next_run), "MM/dd HH:mm")
                  : "—"}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
