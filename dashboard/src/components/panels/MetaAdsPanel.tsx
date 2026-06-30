"use client";

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
      : s.includes("error") || s.includes("disapproved")
      ? "bg-red-500"
      : "bg-jarvis-muted";
  return <span className={`inline-block w-2 h-2 rounded-full ${color} mr-1.5 flex-shrink-0`} />;
}

export function MetaAdsPanel() {
  const { data, error, mutate } = useSWR<Summary>(
    `${HERMES}/api/v1/meta-ads/summary`,
    fetcher,
    { refreshInterval: 60_000 }
  );

  const loading = !data && !error;
  const stale = data?.stale || error;

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-lg">📊</span>
          <h2 className="text-jarvis-text font-semibold text-sm">Meta Ads — Live</h2>
          {stale && !loading && (
            <span className="text-xs text-amber-400 ml-1">(no data)</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-jarvis-muted text-xs">
            {data?.last_updated ? timeSince(data.last_updated) : "—"}
          </span>
          <button
            onClick={() => mutate()}
            className="text-jarvis-muted hover:text-jarvis-accent text-xs"
          >
            ↻
          </button>
        </div>
      </div>

      {loading && (
        <div className="text-jarvis-muted text-sm animate-pulse">Loading ad data…</div>
      )}

      {!loading && stale && (
        <div className="text-jarvis-muted text-sm">
          No data yet. Run the scraper on your RDP machines to start seeing live ads.
        </div>
      )}

      {!loading && data && !data.stale && (
        <>
          {/* Top-level totals */}
          <div className="grid grid-cols-5 gap-3 mb-4">
            {[
              { label: "Spend Today", value: `$${fmt(data.total_spend)}` },
              { label: "Impressions", value: fmt(data.total_impressions, 0) },
              { label: "Clicks", value: fmt(data.total_clicks, 0) },
              { label: "Avg CTR", value: `${fmt(data.avg_ctr)}%` },
              { label: "Active Campaigns", value: String(data.active_campaigns) },
            ].map(({ label, value }) => (
              <div key={label} className="bg-jarvis-bg rounded-lg p-2 text-center">
                <div className="text-jarvis-accent font-mono font-bold text-sm">{value}</div>
                <div className="text-jarvis-muted text-xs mt-0.5">{label}</div>
              </div>
            ))}
          </div>

          {/* Per-profile breakdown */}
          <div className="space-y-3">
            {data.profiles.map((profile) => (
              <div
                key={profile.profile_id}
                className="border border-jarvis-border rounded-lg p-3"
              >
                {/* Profile header */}
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="text-jarvis-text text-xs font-medium">
                      {profile.profile_name || profile.profile_id}
                    </span>
                    {profile.ad_account_name && (
                      <span className="text-jarvis-muted text-xs ml-2">
                        · {profile.ad_account_name}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-jarvis-muted text-xs">{profile.rdp_host}</span>
                    {profile.error && (
                      <span className="text-red-400 text-xs" title={profile.error}>
                        ⚠ error
                      </span>
                    )}
                  </div>
                </div>

                {/* Profile summary row */}
                <div className="grid grid-cols-4 gap-2 mb-2">
                  {[
                    { label: "Spend", value: `$${fmt(profile.summary.total_spend)}` },
                    { label: "Impressions", value: fmt(profile.summary.total_impressions, 0) },
                    { label: "Clicks", value: fmt(profile.summary.total_clicks, 0) },
                    {
                      label: "CTR",
                      value: profile.summary.avg_ctr != null
                        ? `${fmt(profile.summary.avg_ctr)}%`
                        : "—",
                    },
                  ].map(({ label, value }) => (
                    <div key={label} className="bg-jarvis-bg/50 rounded p-1.5 text-center">
                      <div className="text-jarvis-text font-mono text-xs font-semibold">{value}</div>
                      <div className="text-jarvis-muted text-xs">{label}</div>
                    </div>
                  ))}
                </div>

                {/* Campaigns list */}
                {profile.campaigns.length > 0 && (
                  <div className="space-y-1 mt-2">
                    {profile.campaigns.slice(0, 8).map((c, i) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <div className="flex items-center min-w-0">
                          <StatusDot status={c.status} />
                          <span className="text-jarvis-text truncate max-w-[200px]">
                            {c.name || `Campaign ${i + 1}`}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 ml-2 flex-shrink-0 text-jarvis-muted font-mono">
                          {c.spend && <span className="text-jarvis-accent">{c.spend}</span>}
                          {c.impressions && <span>{c.impressions} impr</span>}
                          {c.ctr && <span>{c.ctr} CTR</span>}
                        </div>
                      </div>
                    ))}
                    {profile.campaigns.length > 8 && (
                      <div className="text-jarvis-muted text-xs">
                        +{profile.campaigns.length - 8} more campaigns
                      </div>
                    )}
                  </div>
                )}

                {profile.campaigns.length === 0 && !profile.error && (
                  <div className="text-jarvis-muted text-xs">No campaigns found</div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
