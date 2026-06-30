"use client";

import useSWR from "swr";

interface RDPHost {
  id: string;
  name: string;
  ip: string;
  port: number;
  username: string;
  online: boolean;
  latency_ms: number | null;
  error: string | null;
}

interface RDPStatusResponse {
  ok: boolean;
  summary: string;
  hosts: RDPHost[];
}

const HERMES = process.env.NEXT_PUBLIC_HERMES_URL ?? "http://localhost:8001";
const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function RDPPanel() {
  const { data, error, isLoading } = useSWR<RDPStatusResponse>(
    `${HERMES}/api/v1/rdp/status`,
    fetcher,
    { refreshInterval: 30_000 }
  );

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider">
          Remote Machines
        </h2>
        {data?.summary && (
          <span className="text-xs font-mono text-jarvis-muted px-2 py-0.5 rounded-full border border-jarvis-border">
            {data.summary}
          </span>
        )}
      </div>

      {isLoading && (
        <p className="text-jarvis-muted text-sm animate-pulse">Checking connections...</p>
      )}

      {error && (
        <p className="text-jarvis-red text-sm">Cannot reach Hermes.</p>
      )}

      {!isLoading && !error && data?.hosts && (
        <div className="space-y-0">
          {data.hosts.map((host) => (
            <div
              key={host.id}
              className="flex items-center justify-between py-3 border-b border-jarvis-border/50 last:border-0"
            >
              <div className="min-w-0 flex-1">
                <div className="text-jarvis-text text-sm font-medium">{host.name}</div>
                <div className="text-jarvis-muted text-xs font-mono mt-0.5">{host.ip}:{host.port} · {host.username}</div>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {host.online && host.latency_ms !== null && (
                  <span className="text-xs font-mono text-jarvis-muted">
                    {host.latency_ms}ms
                  </span>
                )}
                <div className="flex items-center gap-1.5">
                  <div
                    className={`w-2 h-2 rounded-full ${
                      host.online ? "bg-jarvis-green status-live" : "bg-jarvis-red"
                    }`}
                  />
                  <span
                    className={`text-xs font-mono ${
                      host.online ? "text-jarvis-green" : "text-jarvis-red"
                    }`}
                  >
                    {host.online ? "online" : host.error === "timeout" ? "timeout" : "offline"}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 pt-3 border-t border-jarvis-border/50">
        <p className="text-jarvis-muted text-xs font-mono">
          Connect via tunnel: localhost:13389 / localhost:23389
        </p>
      </div>
    </div>
  );
}
