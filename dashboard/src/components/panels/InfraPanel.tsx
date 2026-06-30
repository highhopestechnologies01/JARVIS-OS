import { hermesApi } from "@/lib/api";

interface ServiceCheck {
  database: string;
  [key: string]: string;
}

export async function InfraPanel() {
  let health: { status: string; checks: ServiceCheck } | null = null;
  let error = false;

  try {
    health = await hermesApi<{ status: string; checks: ServiceCheck }>("/api/v1/health/ready");
  } catch {
    error = true;
  }

  const services = [
    { name: "Hermes", key: "hermes", always: !error },
    { name: "PostgreSQL", key: "database", status: health?.checks?.database },
    { name: "n8n", key: "n8n" },
    { name: "Prometheus", key: "prometheus" },
    { name: "Grafana", key: "grafana" },
  ];

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider mb-4">
        Infrastructure
      </h2>

      <div className="space-y-2">
        {services.map((svc) => {
          const isOk =
            svc.always ||
            svc.status === "ok" ||
            (!error && !svc.status);

          return (
            <div
              key={svc.name}
              className="flex items-center justify-between py-2 border-b border-jarvis-border/50 last:border-0"
            >
              <span className="text-jarvis-text text-sm">{svc.name}</span>
              <div className="flex items-center gap-2">
                <div
                  className={`w-2 h-2 rounded-full ${
                    error
                      ? "bg-jarvis-red"
                      : isOk
                      ? "bg-jarvis-green status-live"
                      : "bg-jarvis-red"
                  }`}
                />
                <span
                  className={`text-xs font-mono ${
                    error || !isOk
                      ? "text-jarvis-red"
                      : "text-jarvis-green"
                  }`}
                >
                  {error ? "unknown" : isOk ? "running" : "error"}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {error && (
        <p className="text-jarvis-muted text-xs mt-3">
          Cannot reach Hermes. Is the VPS running?
        </p>
      )}
    </div>
  );
}
