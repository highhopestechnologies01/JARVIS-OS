import { hermesApi } from "@/lib/api";

interface Memory {
  id: string;
  type: string;
  topic?: string;
  content: string;
  importance: number;
  created_at: string;
}

export async function MemoryPanel() {
  let memories: Memory[] = [];
  let error = false;

  try {
    memories = await hermesApi<Memory[]>("/api/v1/memory/recent?limit=8");
  } catch {
    error = true;
  }

  const typeColors: Record<string, string> = {
    person: "text-purple-400 bg-purple-400/10",
    project: "text-blue-400 bg-blue-400/10",
    event: "text-jarvis-yellow bg-jarvis-yellow/10",
    fact: "text-jarvis-green bg-jarvis-green/10",
    preference: "text-pink-400 bg-pink-400/10",
  };

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider mb-4">
        Memory
      </h2>

      {error ? (
        <p className="text-jarvis-muted text-sm">Memory unavailable.</p>
      ) : memories.length === 0 ? (
        <p className="text-jarvis-muted text-sm">No memories stored yet.</p>
      ) : (
        <div className="space-y-3 max-h-64 overflow-y-auto">
          {memories.map((m) => (
            <div key={m.id} className="group">
              <div className="flex items-start gap-2">
                <span
                  className={`text-xs px-1.5 py-0.5 rounded shrink-0 font-mono mt-0.5 ${
                    typeColors[m.type] ?? "text-jarvis-muted bg-jarvis-muted/10"
                  }`}
                >
                  {m.type}
                </span>
                <div className="min-w-0">
                  {m.topic && (
                    <div className="text-jarvis-text text-xs font-medium mb-0.5">{m.topic}</div>
                  )}
                  <div className="text-jarvis-muted text-xs leading-relaxed line-clamp-2">
                    {m.content}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
