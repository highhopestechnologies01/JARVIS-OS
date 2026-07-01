"use client";

import { useState } from "react";
import useSWR from "swr";

const HERMES = process.env.NEXT_PUBLIC_HERMES_URL || "http://localhost:8001";
const fetcher = (url: string) => fetch(url).then((r) => r.json());

interface Campaign {
  name?: string;
  status?: string;
  budget?: string;
  spend?: string;
  impressions?: string;
  clicks?: string;
  ctr?: string;
  cpc?: string;
  cpm?: string;
  results?: string;
  reach?: string;
  profile_name?: string;
  ad_account_name?: string;
  rdp_host?: string;
  [key: string]: string | undefined;
}

interface Profile {
  profile_id: string;
  profile_name?: string;
  ad_account_id?: string;
  ad_account_name?: string;
  rdp_host: string;
  scraped_at?: string;
  campaigns: Campaign[];
  summary: {
    total_spend?: number;
    total_spend_all?: number;
    total_campaigns?: number;
    total_impressions?: number;
    total_clicks?: number;
    active_campaigns?: number;
    avg_ctr?: number;
    [key: string]: number | undefined;
  };
  error?: string;
}

interface Summary {
  total_spend: number;
  total_impressions: number;
  total_clicks: number;
  avg_ctr: number;
  active_campaigns: number;
  profiles_count: number;
  last_updated?: string;
  profiles: Profile[];
  stale: boolean;
}

interface Control {
  enabled: boolean;
  updated_at?: string;
}

function fmt(n: number | undefined, decimals = 2): string {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString("en-US", { maximumFractionDigits: decimals });
}

function timeSince(iso?: string): string {
  if (!iso) return "never";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function StatusDot({ status }: { status?: string }) {
  const s = (status || "").toLowerCase();
  const color =
    s.includes("active") || s.includes("delivering")
      ? "bg-emerald-500"
      : s.includes("paused")
      ? "bg-amber-400"
      : s.includes("draft")
      ? "bg-blue-400"
      : s.includes("error") || s.includes("disapproved")
      ? "bg-red-500"
      : "bg-jarvis-muted";
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${color} mr-1.5 flex-shrink-0`}
    />
  );
}

function Toggle({
  enabled,
  loading,
  onChange,
}: {
  enabled: boolean;
  loading: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => !loading && onChange(!enabled)}
      disabled={loading}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus:outline-none
        ${enabled ? "bg-emerald-500" : "bg-jarvis-muted/40"}
        ${loading ? "opacity-50 cursor-wait" : "cursor-pointer"}`}
      title={enabled ? "Scraper ON — click to disable" : "Scraper OFF — click to enable"}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200
          ${enabled ? "translate-x-4.5" : "translate-x-0.5"}`}
      />
    </button>
  );
}

// Group profiles by RDP host
function byRdp(profiles: Profile[]): Record<string, Profile[]> {
  const out: Record<string, Profile[]> = {};
  for (const p of profiles) {
    (out[p.rdp_host] ??= []).push(p);
  }
  return out;
}

export function MetaAdsPanel() {
  const [toggling, setToggling] = useState(false);

  const {
    data: summary,
    error: summaryErr,
    mutate: mutateSummary,
  } = useSWR<Summary>(`${HERMES}/api/v1/meta-ads/summary`, fetcher, {
    refreshInterval: 30_000,
  });

  const {
    data: control,
    mutate: mutateControl,
  } = useSWR<Control>(`${HERMES}/api/v1/meta-ads/control`, fetcher, {
    refreshInterval: 5_000,
  });

  const loading = !summary && !summaryErr;
  const stale = summary?.stale || summaryErr;
  const scraperEnabled = control?.enabled ?? true;

  async function toggleScraper(enabled: boolean) {
    setToggling(true);
    try {
      await fetch(`${HERMES}/api/v1/meta-ads/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      await mutateControl();
    } finally {
      setToggling(false);
    }
  }

  // Get last scrape time per RDP machine
  const rdpLastSeen: Record<string, string> = {};
  for (const p of summary?.profiles ?? []) {
    if (p.scraped_at) {
      const cur = rdpLastSeen[p.rdp_host];
      if (!cur || p.scraped_at > cur) rdpLastSeen[p.rdp_host] = p.scraped_at;
    }
  }

  const grouped = byRdp(summary?.profiles ?? []);
  const rdpHosts = Object.keys(grouped).sort();

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-lg">📊</span>
          <h2 className="text-jarvis-text font-semibold text-sm">Meta Ads</h2>
          {/* Scraper status badge */}
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              scraperEnabled
                ? "bg-emerald-500/15 text-emerald-400"
                : "bg-amber-500/15 text-amber-400"
            }`}
          >
            {scraperEnabled ? "● Scraping" : "● Paused"}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Scraper on/off toggle */}
          <div className="flex items-center gap-1.5">
            <span className="text-jarvis-muted text-xs">
              {scraperEnabled ? "ON" : "OFF"}
            </span>
            <Toggle
              enabled={scraperEnabled}
              loading={toggling}
              onChange={toggleScraper}
            />
          </div>

          <span className="text-jarvis-muted text-xs">
            {summary?.last_updated ? timeSince(summary.last_updated) : "—"}
          </span>
          <button
            onClick={() => { mutateSummary(); mutateControl(); }}
            className="text-jarvis-muted hover:text-jarvis-accent text-xs"
          >
            ↻
          </button>
        </div>
      </div>

      {/* ── RDP Machine Status Row ── */}
      {(rdpHosts.length > 0 || !loading) && (
        <div className="flex gap-2 mb-4">
          {["RDP-1", "RDP-2"].map((rdp) => {
            const lastSeen = rdpLastSeen[rdp];
            const minsAgo = lastSeen
              ? Math.floor((Date.now() - new Date(lastSeen).getTime()) / 60000)
              : null;
            const online = minsAgo != null && minsAgo < 10;
            return (
              <div
                key={rdp}
                className="flex-1 bg-jarvis-bg rounded-lg px-3 py-2 flex items-center justify-between"
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      online ? "bg-emerald-500" : lastSeen ? "bg-amber-400" : "bg-jarvis-muted/40"
                    }`}
                  />
                  <span className="text-jarvis-text text-xs font-medium">{rdp}</span>
                </div>
                <span className="text-jarvis-muted text-xs">
                  {lastSeen ? timeSince(lastSeen) : "no data"}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {loading && (
        <div className="text-jarvis-muted text-sm animate-pulse">Loading ad data…</div>
      )}

      {!loading && stale && (
        <div className="text-jarvis-muted text-sm">
          No recent data.{" "}
          {scraperEnabled
            ? "Waiting for next scrape (every 5 min)."
            : "Scraper is paused — enable it above to start collecting data."}
        </div>
      )}

      {!loading && summary && !summary.stale && (
        <>
          {/* ── Global totals ── */}
          <div className="grid grid-cols-5 gap-2 mb-4">
            {[
              { label: "Total Spend", value: `$${fmt(summary.total_spend)}` },
              { label: "Impressions", value: fmt(summary.total_impressions, 0) },
              { label: "Clicks", value: fmt(summary.total_clicks, 0) },
              { label: "Avg CTR", value: `${fmt(summary.avg_ctr)}%` },
              { label: "Campaigns", value: String(summary.active_campaigns || summary.profiles_count) },
            ].map(({ label, value }) => (
              <div
                key={label}
                className="bg-jarvis-bg rounded-lg p-2 text-center"
              >
                <div className="text-jarvis-accent font-mono font-bold text-sm">
                  {value}
                </div>
                <div className="text-jarvis-muted text-xs mt-0.5">{label}</div>
              </div>
            ))}
          </div>

          {/* ── Per-RDP sections ── */}
          {rdpHosts.map((rdp) => (
            <div key={rdp} className="mb-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-jarvis-muted text-xs font-semibold uppercase tracking-wider">
                  {rdp}
                </span>
                <div className="h-px flex-1 bg-jarvis-border" />
              </div>

              <div className="space-y-2">
                {grouped[rdp].map((profile) => {
                  const spend =
                    profile.summary.total_spend_all ??
                    profile.summary.total_spend;
                  const campaignCount =
                    profile.summary.total_campaigns ??
                    profile.campaigns.length;

                  return (
                    <div
                      key={profile.profile_id}
                      className="border border-jarvis-border rounded-lg p-3"
                    >
                      {/* Profile header */}
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="text-jarvis-text text-xs font-medium truncate">
                            {profile.profile_name || profile.profile_id}
                          </span>
                          {profile.ad_account_id && (
                            <span className="text-jarvis-muted text-xs font-mono flex-shrink-0">
                              ·{" "}
                              {profile.ad_account_id.slice(-6)}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {profile.error && (
                            <span
                              className="text-red-400 text-xs"
                              title={profile.error}
                            >
                              ⚠
                            </span>
                          )}
                          <span className="text-jarvis-muted text-xs">
                            {profile.scraped_at
                              ? timeSince(profile.scraped_at)
                              : "—"}
                          </span>
                        </div>
                      </div>

                      {/* Spend + campaign count */}
                      <div className="flex items-end gap-4 mb-2">
                        <div>
                          <div className="text-jarvis-accent font-mono font-bold text-xl leading-none">
                            ${spend != null ? fmt(spend) : "—"}
                          </div>
                          <div className="text-jarvis-muted text-xs mt-0.5">
                            total spend
                          </div>
                        </div>
                        <div>
                          <div className="text-jarvis-text font-mono font-semibold text-base leading-none">
                            {campaignCount ?? "—"}
                          </div>
                          <div className="text-jarvis-muted text-xs mt-0.5">
                            campaigns
                          </div>
                        </div>
                        {profile.summary.total_impressions != null && (
                          <div>
                            <div className="text-jarvis-text font-mono text-base leading-none">
                              {fmt(profile.summary.total_impressions, 0)}
                            </div>
                            <div className="text-jarvis-muted text-xs mt-0.5">
                              impressions
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Campaign rows */}
                      {profile.campaigns.length > 0 && (
                        <div className="space-y-1 border-t border-jarvis-border/50 pt-2 mt-2">
                          {profile.campaigns.slice(0, 6).map((c, i) => (
                            <div
                              key={i}
                              className="flex items-center justify-between text-xs"
                            >
                              <div className="flex items-center min-w-0">
                                <StatusDot status={c.status} />
                                <span className="text-jarvis-text truncate max-w-[180px]">
                                  {c.name || `Campaign ${i + 1}`}
                                </span>
                                {c.status?.toLowerCase().includes("draft") && (
                                  <span className="ml-1 text-blue-400 text-xs">(draft)</span>
                                )}
                              </div>
                              <div className="flex items-center gap-3 ml-2 flex-shrink-0 text-jarvis-muted font-mono">
                                {c.spend && (
                                  <span className="text-jarvis-accent">
                                    {c.spend}
                                  </span>
                                )}
                                {c.impressions && (
                                  <span>{c.impressions} impr</span>
                                )}
                                {c.ctr && <span>{c.ctr} CTR</span>}
                              </div>
                            </div>
                          ))}
                          {profile.campaigns.length > 6 && (
                            <div className="text-jarvis-muted text-xs pt-0.5">
                              +{profile.campaigns.length - 6} more
                            </div>
                          )}
                        </div>
                      )}

                      {profile.campaigns.length === 0 && !profile.error && (
                        <div className="text-jarvis-muted text-xs">
                          No campaigns captured
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
