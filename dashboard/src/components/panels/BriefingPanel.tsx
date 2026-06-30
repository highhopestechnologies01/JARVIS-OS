import { hermesApi } from "@/lib/api";

type Briefing = { date: string; content: string; summary?: string; status: string };

export async function BriefingPanel() {
  let briefing: Briefing | null = null;
  let error = false;

  try {
    briefing = await hermesApi<Briefing>("/api/v1/briefings/today");
  } catch {
    error = true;
  }

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5 h-full min-h-[300px]">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider">
            Today&apos;s Briefing
          </h2>
          {briefing && (
            <div className="text-jarvis-muted text-xs mt-0.5">{briefing.date}</div>
          )}
        </div>
        <StatusBadge status={briefing?.status} error={error} />
      </div>

      {error ? (
        <div className="text-jarvis-muted text-sm">
          Unable to connect to Hermes. Check infrastructure status.
        </div>
      ) : !briefing ? (
        <div className="text-jarvis-muted text-sm">No briefing available.</div>
      ) : (
        <div className="prose prose-invert prose-sm max-w-none text-jarvis-text/90 leading-relaxed whitespace-pre-wrap text-sm">
          {briefing.content}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status, error }: { status?: string | null; error: boolean }) {
  if (error) return <span className="text-xs text-jarvis-red bg-jarvis-red/10 px-2 py-1 rounded">offline</span>;
  if (!status) return null;
  const color = status === "delivered" ? "text-jarvis-green bg-jarvis-green/10" : "text-jarvis-yellow bg-jarvis-yellow/10";
  return <span className={`text-xs px-2 py-1 rounded ${color}`}>{status}</span>;
}
