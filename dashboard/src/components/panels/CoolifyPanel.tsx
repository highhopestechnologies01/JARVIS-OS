"use client";

import useSWR from "swr";
import { useState } from "react";

interface CoolifyServer {
  uuid: string;
  name: string;
  is_reachable: boolean;
  is_usable: boolean;
  is_coolify_host?: boolean;
}

interface CoolifyService {
  uuid: string;
  name: string;
  status?: string;
}

interface CoolifyApplication {
  uuid: string;
  name: string;
  status?: string;
}

interface CoolifyData {
  version: string | null;
  servers: CoolifyServer[];
  services: CoolifyService[];
  applications: CoolifyApplication[];
}

interface CoolifyResponse {
  ok: boolean;
  data: CoolifyData;
}

const HERMES = process.env.NEXT_PUBLIC_HERMES_URL ?? "http://localhost:8001";
const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function CoolifyPanel() {
  const { data, error, isLoading, mutate } = useSWR<CoolifyResponse>(
    `${HERMES}/api/v1/coolify/status`,
    fetcher,
    { refreshInterval: 60_000 }
  );

  const [restarting, setRestarting] = useState<string | null>(null);
  const [restartMsg, setRestartMsg] = useState<string | null>(null);

  const restartService = async (uuid: string, name: string) => {
    setRestarting(uuid);
    setRestartMsg(null);
    try {
      const res = await fetch(
        `${HERMES}/api/v1/coolify/services/${uuid}/restart`,
        { method: "POST" }
      );
      setRestartMsg(res.ok ? `✓ ${name} restart triggered` : `✗ Failed to restart ${name}`);
    } catch {
      setRestartMsg("✗ Restart failed");
    } finally {
      setRestarting(null);
      setTimeout(() => setRestartMsg(null), 4000);
      mutate();
    }
  };

  const coolify = data?.data;

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-jarvis-text font-semibold text-sm uppercase tracking-wider">
          Deployments
        </h2>
        {coolify?.version && (
          <span className="text-xs font-mono text-jarvis-muted px-2 py-0.5 rounded-full border border-jarvis-border">
            Coolify {coolify.version}
          </span>
        )}
      </div>

      {isLoading && (
        <p className="text-jarvis-muted text-sm animate-pulse">
          Fetching deployment state...
        </p>
      )}

      {error && (
        <p className="text-jarvis-red text-sm">Coolify unreachable.</p>
      )}

      {!isLoading && !error && coolify && (
        <div className="space-y-4">
          {/* Servers */}
          {coolify.servers.length > 0 && (
            <div>
              <p className="text-jarvis-muted text-xs uppercase tracking-wider mb-2">
                Servers
              </p>
              <div className="space-y-0">
                {coolify.servers.map((server) => (
                  <div
                    key={server.uuid}
                    className="flex items-center justify-between py-2 border-b border-jarvis-border/50 last:border-0"
                  >
                    <span className="text-jarvis-text text-sm">{server.name}</span>
                    <div className="flex items-center gap-2">
                      <div
                        className={`w-2 h-2 rounded-full ${
                          server.is_reachable
                            ? "bg-jarvis-green status-live"
                            : "bg-jarvis-red"
                        }`}
                      />
                      <span
                        className={`text-xs font-mono ${
                          server.is_reachable ? "text-jarvis-green" : "text-jarvis-red"
                        }`}
                      >
                        {server.is_reachable ? "reachable" : "unreachable"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Services */}
          {coolify.services.length > 0 && (
            <div>
              <p className="text-jarvis-muted text-xs uppercase tracking-wider mb-2">
                Services
              </p>
              <div className="space-y-0">
                {coolify.services.map((svc) => (
                  <div
                    key={svc.uuid}
                    className="flex items-center justify-between py-2 border-b border-jarvis-border/50 last:border-0 gap-2"
                  >
                    <span className="text-jarvis-text text-sm truncate">
                      {svc.name}
                    </span>
                    <button
                      onClick={() => restartService(svc.uuid, svc.name)}
                      disabled={restarting === svc.uuid}
                      className="shrink-0 text-xs px-2 py-1 rounded border border-jarvis-accent/40
                        text-jarvis-accent hover:bg-jarvis-accent/10 transition-colors
                        disabled:opacity-40 disabled:cursor-not-allowed font-mono"
                    >
                      {restarting === svc.uuid ? "..." : "↺ restart"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Applications */}
          {coolify.applications.length > 0 && (
            <div>
              <p className="text-jarvis-muted text-xs uppercase tracking-wider mb-2">
                Applications
              </p>
              <div className="space-y-0">
                {coolify.applications.map((app) => (
                  <div
                    key={app.uuid}
                    className="flex items-center justify-between py-2 border-b border-jarvis-border/50 last:border-0 gap-2"
                  >
                    <span className="text-jarvis-text text-sm truncate">
                      {app.name}
                    </span>
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-jarvis-green status-live" />
                      <span className="text-xs font-mono text-jarvis-green">running</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {coolify.servers.length === 0 &&
            coolify.services.length === 0 &&
            coolify.applications.length === 0 && (
              <p className="text-jarvis-muted text-sm">No deployments found.</p>
            )}
        </div>
      )}

      {restartMsg && (
        <div
          className={`mt-3 text-xs font-mono px-3 py-2 rounded border ${
            restartMsg.startsWith("✓")
              ? "text-jarvis-green border-jarvis-green/20 bg-jarvis-green/5"
              : "text-jarvis-red border-jarvis-red/20 bg-jarvis-red/5"
          }`}
        >
          {restartMsg}
        </div>
      )}
    </div>
  );
}
