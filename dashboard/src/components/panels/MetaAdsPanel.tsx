"use client";

import { useState, useEffect, useCallback } from "react";
import useSWR from "swr";

const HERMES = "";
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
  profile_id?: string;
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
  date?: string;
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

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
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
    <span className={`inline-block w-2 h-2 rounded-full ${color} mr-1.5 flex-shrink-0`} />
  );
}

function ScraperToggle({
  enabled, loading, onChange,
}: { enabled: boolean; loading: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => !loading && onChange(!enabled)}
      disabled={loading}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus:outline-none
        ${enabled ? "bg-emerald-500" : "bg-jarvis-muted/40"}
        ${loading ? "opacity-50 cursor-wait" : "cursor-pointer"}`}
      title={enabled ? "Scraper ON — click to disable" : "Scraper OFF — click to enable"}
    >
      <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200
        ${enabled ? "translate-x-4.5" : "translate-x-0.5"}`} />
    </button>
  );
}

function CampaignToggleBtn({
  campaign, profileId, rdpHost, onDone,
}: {
  campaign: Campaign;
  profileId: string;
  rdpHost: string;
  onDone: () => void;
}) {
  const [pending, setPending] = useState(false);
  const isActive = (campaign.status || "").toLowerCase().includes("active") ||
    (campaign.status || "").toLowerCase().includes("delivering");

  async function handleToggle() {
    if (pending) return;
    setPending(true);
    try {
      const action = isActive ? "PAUSE" : "ACTIVATE";
      await fetch(`${HERMES}/api/v1/meta-ads/commands`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rdp_host: rdpHost,
          profile_id: profileId,
          campaign_name: campaign.name || "",
          action,
        }),
      });
      onDone();
    } finally {
      setPending(false);
    }
  }

  return (
    <button
      onClick={handleToggle}
      disabled={pending}
      title={isActive ? "Pause campaign" : "Activate campaign"}
      className={`text-xs px-2 py-0.5 rounded font-medium transition-colors flex-shrink-0
        ${pending ? "opacity-50 cursor-wait" : "cursor-pointer"}
        ${isActive
          ? "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30"
          : "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30"
        }`}
    >
      {pending ? "…" : isActive ? "Pause" : "Activate"}
    </button>
  );
}

interface BudgetConfig {
  enabled: boolean;
  total_daily_cap: number;
  alert_pct: number;
  auto_pause_pct: number;
  stopped_detection: boolean;
  alert_cooldown_hours: number;
  campaign_budgets: Record<string, number>;
}

const DEFAULT_BUDGET_CONFIG: BudgetConfig = {
  enabled: true,
  total_daily_cap: 0,
  alert_pct: 80,
  auto_pause_pct: 100,
  stopped_detection: true,
  alert_cooldown_hours: 4,
  campaign_budgets: {},
};

function BudgetConfigPanel({ hermes }: { hermes: string }) {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState<BudgetConfig>(DEFAULT_BUDGET_CONFIG);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [newCampaign, setNewCampaign] = useState("");
  const [newBudget, setNewBudget] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${hermes}/api/v1/meta-ads/budget-config`);
      if (r.ok) setCfg(await r.json());
    } catch { /* ignore */ }
  }, [hermes]);

  useEffect(() => { if (open) load(); }, [open, load]);

  async function save() {
    setSaving(true);
    setSaved(false);
    try {
      await fetch(`${hermes}/api/v1/meta-ads/budget-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  function addCampaignBudget() {
    const name = newCampaign.trim();
    const budget = parseFloat(newBudget);
    if (!name || isNaN(budget) || budget <= 0) return;
    setCfg((c) => ({ ...c, campaign_budgets: { ...c.campaign_budgets, [name]: budget } }));
    setNewCampaign("");
    setNewBudget("");
  }

  function removeCampaignBudget(name: string) {
    setCfg((c) => {
      const b = { ...c.campaign_budgets };
      delete b[name];
      return { ...c, campaign_budgets: b };
    });
  }

  return (
    <div className="border border-jarvis-border rounded-lg mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs text-jarvis-muted hover:text-jarvis-text transition-colors"
      >
        <span className="flex items-center gap-1.5">⚙️ <span className="font-medium">Budget & Alert Config</span></span>
        <span>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-3 border-t border-jarvis-border/50 pt-3">
          {/* Master enable */}
          <div className="flex items-center justify-between">
            <span className="text-jarvis-text text-xs font-medium">Spend Alerts Enabled</span>
            <button
              onClick={() => setCfg((c) => ({ ...c, enabled: !c.enabled }))}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
                ${cfg.enabled ? "bg-emerald-500" : "bg-jarvis-muted/40"}`}
            >
              <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform
                ${cfg.enabled ? "translate-x-4.5" : "translate-x-0.5"}`} />
            </button>
          </div>

          {/* Numeric thresholds */}
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: "Alert at %", key: "alert_pct" as const, hint: "Send alert when spend hits this % of budget" },
              { label: "Auto-pause at %", key: "auto_pause_pct" as const, hint: "Queue PAUSE when spend hits this %" },
              { label: "Daily Cap $", key: "total_daily_cap" as const, hint: "Alert when total daily spend hits this (0 = off)" },
              { label: "Cooldown (hrs)", key: "alert_cooldown_hours" as const, hint: "Suppress repeat alerts for the same campaign within this many hours" },
            ].map(({ label, key, hint }) => (
              <div key={key}>
                <label className="text-jarvis-muted text-xs block mb-1" title={hint}>{label}</label>
                <input
                  type="number"
                  min={0}
                  step={key === "total_daily_cap" ? 10 : 5}
                  value={cfg[key]}
                  onChange={(e) => setCfg((c) => ({ ...c, [key]: parseFloat(e.target.value) || 0 }))}
                  className="w-full bg-jarvis-bg border border-jarvis-border rounded px-2 py-1 text-xs text-jarvis-text focus:outline-none focus:border-jarvis-accent"
                />
              </div>
            ))}
          </div>

          {/* Stopped detection */}
          <div className="flex items-center justify-between">
            <span className="text-jarvis-muted text-xs" title="Alert when a campaign was spending last cycle but is now $0">
              Detect campaigns that suddenly stop spending
            </span>
            <button
              onClick={() => setCfg((c) => ({ ...c, stopped_detection: !c.stopped_detection }))}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors flex-shrink-0
                ${cfg.stopped_detection ? "bg-emerald-500" : "bg-jarvis-muted/40"}`}
            >
              <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform
                ${cfg.stopped_detection ? "translate-x-4.5" : "translate-x-0.5"}`} />
            </button>
          </div>

          {/* Per-campaign budgets */}
          <div>
            <div className="text-jarvis-muted text-xs font-medium mb-1.5">Per-Campaign Daily Budgets</div>
            <div className="space-y-1 mb-2">
              {Object.entries(cfg.campaign_budgets).map(([name, budget]) => (
                <div key={name} className="flex items-center gap-2 text-xs">
                  <span className="text-jarvis-text flex-1 truncate">{name}</span>
                  <span className="text-jarvis-accent font-mono flex-shrink-0">${budget}</span>
                  <button
                    onClick={() => removeCampaignBudget(name)}
                    className="text-red-400/70 hover:text-red-400 flex-shrink-0"
                  >✕</button>
                </div>
              ))}
              {Object.keys(cfg.campaign_budgets).length === 0 && (
                <div className="text-jarvis-muted text-xs italic">No per-campaign budgets set — alerts won&apos;t fire unless you add budgets here</div>
              )}
            </div>
            <div className="flex gap-1.5">
              <input
                type="text"
                placeholder="Campaign name (exact)"
                value={newCampaign}
                onChange={(e) => setNewCampaign(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addCampaignBudget()}
                className="flex-1 bg-jarvis-bg border border-jarvis-border rounded px-2 py-1 text-xs text-jarvis-text placeholder-jarvis-muted focus:outline-none focus:border-jarvis-accent"
              />
              <input
                type="number"
                placeholder="$ /day"
                value={newBudget}
                onChange={(e) => setNewBudget(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addCampaignBudget()}
                className="w-20 bg-jarvis-bg border border-jarvis-border rounded px-2 py-1 text-xs text-jarvis-text placeholder-jarvis-muted focus:outline-none focus:border-jarvis-accent"
              />
              <button
                onClick={addCampaignBudget}
                className="text-jarvis-accent text-xs px-2 py-1 border border-jarvis-accent/40 rounded hover:bg-jarvis-accent/10 flex-shrink-0"
              >+ Add</button>
            </div>
          </div>

          {/* Save button */}
          <button
            onClick={save}
            disabled={saving}
            className={`w-full py-1.5 rounded text-xs font-medium transition-colors
              ${saved
                ? "bg-emerald-500/20 text-emerald-400"
                : saving
                ? "bg-jarvis-muted/20 text-jarvis-muted cursor-wait"
                : "bg-jarvis-accent/20 text-jarvis-accent hover:bg-jarvis-accent/30"
              }`}
          >
            {saved ? "✓ Saved" : saving ? "Saving…" : "Save Alert Config"}
          </button>
        </div>
      )}
    </div>
  );
}

interface InsightData {
  summary?: string;
  insights?: string[];
  top_campaign?: string | null;
  concern?: string | null;
}

interface InsightsResponse {
  available: boolean;
  data: InsightData | null;
  updated_at: string | null;
}

function CampaignInsightsPanel({ hermes }: { hermes: string }) {
  const [running, setRunning] = useState(false);
  const { data, mutate } = useSWR<InsightsResponse>(
    `${hermes}/api/v1/meta-ads/insights`,
    fetcher,
    { refreshInterval: 60_000 }
  );

  async function runNow() {
    if (running) return;
    setRunning(true);
    try {
      await fetch(`${hermes}/api/v1/meta-ads/insights/run`, { method: "POST" });
      // Poll for result
      await new Promise((r) => setTimeout(r, 8000));
      await mutate();
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="border border-jarvis-border rounded-lg mt-3">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-xs text-jarvis-text flex items-center gap-1.5">
          🤖 <span className="font-medium">Campaign Insights</span>
          {data?.updated_at && (
            <span className="text-jarvis-muted ml-1">{timeSince(data.updated_at)}</span>
          )}
        </span>
        <button
          onClick={runNow}
          disabled={running}
          className={`text-xs px-2 py-0.5 rounded border transition-colors flex-shrink-0
            ${running
              ? "border-jarvis-muted/30 text-jarvis-muted cursor-wait"
              : "border-jarvis-accent/40 text-jarvis-accent hover:bg-jarvis-accent/10"
            }`}
        >
          {running ? "Analyzing…" : "▶ Run Now"}
        </button>
      </div>

      {data?.available && data.data && (
        <div className="px-3 pb-3 border-t border-jarvis-border/50 pt-2 space-y-2">
          {data.data.summary && (
            <p className="text-jarvis-muted text-xs italic">{data.data.summary}</p>
          )}
          {(data.data.insights || []).map((insight, i) => (
            <div key={i} className="flex gap-2 text-xs">
              <span className="text-jarvis-accent flex-shrink-0">{i + 1}.</span>
              <span className="text-jarvis-text">{insight}</span>
            </div>
          ))}
          {data.data.top_campaign && (
            <div className="flex items-center gap-1.5 text-xs mt-1">
              <span>🏆</span>
              <span className="text-jarvis-muted">Top:</span>
              <span className="text-emerald-400 font-medium">{data.data.top_campaign}</span>
            </div>
          )}
          {data.data.concern && (
            <div className="flex items-center gap-1.5 text-xs">
              <span>⚠️</span>
              <span className="text-amber-400">{data.data.concern}</span>
            </div>
          )}
        </div>
      )}

      {!data?.available && (
        <div className="px-3 pb-3 text-jarvis-muted text-xs border-t border-jarvis-border/50 pt-2">
          No insights yet — click ▶ Run Now or wait for the 9:30am daily job.
        </div>
      )}
    </div>
  );
}

function byRdp(profiles: Profile[]): Record<string, Profile[]> {
  const out: Record<string, Profile[]> = {};
  for (const p of profiles) {
    (out[p.rdp_host] ??= []).push(p);
  }
  return out;
}

export function MetaAdsPanel() {
  const [toggling, setToggling] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string>("");  // "" = live
  const [campaignFilter, setCampaignFilter] = useState("");

  const summaryUrl = selectedDate
    ? `${HERMES}/api/v1/meta-ads/summary?date=${selectedDate}`
    : `${HERMES}/api/v1/meta-ads/summary`;

  const {
    data: summary,
    error: summaryErr,
    mutate: mutateSummary,
  } = useSWR<Summary>(summaryUrl, fetcher, {
    refreshInterval: selectedDate ? 0 : 30_000,
  });

  const { data: control, mutate: mutateControl } = useSWR<Control>(
    `${HERMES}/api/v1/meta-ads/control`,
    fetcher,
    { refreshInterval: 5_000 }
  );

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

  const rdpLastSeen: Record<string, string> = {};
  for (const p of summary?.profiles ?? []) {
    if (p.scraped_at) {
      const cur = rdpLastSeen[p.rdp_host];
      if (!cur || p.scraped_at > cur) rdpLastSeen[p.rdp_host] = p.scraped_at;
    }
  }

  const grouped = byRdp(summary?.profiles ?? []);
  const rdpHosts = Object.keys(grouped).sort();

  // Filter campaigns client-side
  const lcFilter = campaignFilter.toLowerCase();

  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">📊</span>
          <h2 className="text-jarvis-text font-semibold text-sm">Meta Ads</h2>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            scraperEnabled ? "bg-emerald-500/15 text-emerald-400" : "bg-amber-500/15 text-amber-400"
          }`}>
            {scraperEnabled ? "● Scraping" : "● Paused"}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="text-jarvis-muted text-xs">{scraperEnabled ? "ON" : "OFF"}</span>
            <ScraperToggle enabled={scraperEnabled} loading={toggling} onChange={toggleScraper} />
          </div>
          <span className="text-jarvis-muted text-xs">
            {summary?.last_updated ? timeSince(summary.last_updated) : "—"}
          </span>
          <button
            onClick={() => { mutateSummary(); mutateControl(); }}
            className="text-jarvis-muted hover:text-jarvis-accent text-xs"
          >↻</button>
        </div>
      </div>

      {/* ── Date picker + Campaign filter ── */}
      <div className="flex gap-2 mb-3">
        <div className="flex items-center gap-1.5 flex-1">
          <span className="text-jarvis-muted text-xs flex-shrink-0">📅</span>
          <input
            type="date"
            value={selectedDate}
            max={todayStr()}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="flex-1 bg-jarvis-bg border border-jarvis-border rounded px-2 py-1 text-xs text-jarvis-text focus:outline-none focus:border-jarvis-accent"
          />
          {selectedDate && (
            <button
              onClick={() => setSelectedDate("")}
              className="text-jarvis-muted hover:text-jarvis-accent text-xs flex-shrink-0"
              title="Back to live view"
            >✕</button>
          )}
        </div>
        <input
          type="text"
          placeholder="Filter campaigns…"
          value={campaignFilter}
          onChange={(e) => setCampaignFilter(e.target.value)}
          className="flex-1 bg-jarvis-bg border border-jarvis-border rounded px-2 py-1 text-xs text-jarvis-text placeholder-jarvis-muted focus:outline-none focus:border-jarvis-accent"
        />
      </div>

      {/* ── RDP Machine Status Row ── */}
      {!loading && (
        <div className="flex gap-2 mb-4">
          {["RDP-1", "RDP-2"].map((rdp) => {
            const lastSeen = rdpLastSeen[rdp];
            const minsAgo = lastSeen
              ? Math.floor((Date.now() - new Date(lastSeen).getTime()) / 60000)
              : null;
            const online = minsAgo != null && minsAgo < 10;
            return (
              <div key={rdp} className="flex-1 bg-jarvis-bg rounded-lg px-3 py-2 flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${
                    online ? "bg-emerald-500" : lastSeen ? "bg-amber-400" : "bg-jarvis-muted/40"
                  }`} />
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

      {loading && <div className="text-jarvis-muted text-sm animate-pulse">Loading ad data…</div>}

      {!loading && stale && (
        <div className="text-jarvis-muted text-sm">
          {selectedDate ? `No data for ${selectedDate}.` : (
            scraperEnabled
              ? "No recent data. Waiting for next scrape (every 5 min)."
              : "Scraper is paused — enable it above."
          )}
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
              <div key={label} className="bg-jarvis-bg rounded-lg p-2 text-center">
                <div className="text-jarvis-accent font-mono font-bold text-sm">{value}</div>
                <div className="text-jarvis-muted text-xs mt-0.5">{label}</div>
              </div>
            ))}
          </div>

          {/* ── Per-RDP sections ── */}
          {rdpHosts.map((rdp) => (
            <div key={rdp} className="mb-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-jarvis-muted text-xs font-semibold uppercase tracking-wider">{rdp}</span>
                <div className="h-px flex-1 bg-jarvis-border" />
              </div>

              <div className="space-y-2">
                {grouped[rdp].map((profile) => {
                  const spend = profile.summary.total_spend_all ?? profile.summary.total_spend;
                  const campaignCount = profile.summary.total_campaigns ?? profile.campaigns.length;
                  const visibleCampaigns = profile.campaigns.filter((c) =>
                    !lcFilter || (c.name || "").toLowerCase().includes(lcFilter)
                  );

                  return (
                    <div key={profile.profile_id} className="border border-jarvis-border rounded-lg p-3">
                      {/* Profile header */}
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="text-jarvis-text text-xs font-medium truncate">
                            {profile.profile_name || profile.profile_id}
                          </span>
                          {profile.ad_account_id && (
                            <span className="text-jarvis-muted text-xs font-mono flex-shrink-0">
                              · {profile.ad_account_id.slice(-6)}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {profile.error && (
                            <span className="text-red-400 text-xs" title={profile.error}>⚠</span>
                          )}
                          <span className="text-jarvis-muted text-xs">
                            {profile.scraped_at ? timeSince(profile.scraped_at) : "—"}
                          </span>
                        </div>
                      </div>

                      {/* Spend + campaign count */}
                      <div className="flex items-end gap-4 mb-2">
                        <div>
                          <div className="text-jarvis-accent font-mono font-bold text-xl leading-none">
                            ${spend != null ? fmt(spend) : "—"}
                          </div>
                          <div className="text-jarvis-muted text-xs mt-0.5">total spend</div>
                        </div>
                        <div>
                          <div className="text-jarvis-text font-mono font-semibold text-base leading-none">
                            {campaignCount ?? "—"}
                          </div>
                          <div className="text-jarvis-muted text-xs mt-0.5">campaigns</div>
                        </div>
                        {profile.summary.total_impressions != null && (
                          <div>
                            <div className="text-jarvis-text font-mono text-base leading-none">
                              {fmt(profile.summary.total_impressions, 0)}
                            </div>
                            <div className="text-jarvis-muted text-xs mt-0.5">impressions</div>
                          </div>
                        )}
                      </div>

                      {/* Campaign rows with toggle buttons */}
                      {visibleCampaigns.length > 0 && (
                        <div className="space-y-1 border-t border-jarvis-border/50 pt-2 mt-2">
                          {visibleCampaigns.slice(0, 10).map((c, i) => (
                            <div key={i} className="flex items-center justify-between text-xs gap-2">
                              <div className="flex items-center min-w-0 flex-1">
                                <StatusDot status={c.status} />
                                <span className="text-jarvis-text truncate max-w-[160px]">
                                  {c.name || `Campaign ${i + 1}`}
                                </span>
                              </div>
                              <div className="flex items-center gap-2 flex-shrink-0">
                                {c.spend && (
                                  <span className="text-jarvis-accent font-mono">{c.spend}</span>
                                )}
                                {c.budget && (
                                  <span className="text-jarvis-muted font-mono">/{c.budget}</span>
                                )}
                                {c.impressions && (
                                  <span className="text-jarvis-muted font-mono hidden sm:inline">
                                    {c.impressions} impr
                                  </span>
                                )}
                                <CampaignToggleBtn
                                  campaign={c}
                                  profileId={profile.profile_id}
                                  rdpHost={profile.rdp_host}
                                  onDone={mutateSummary}
                                />
                              </div>
                            </div>
                          ))}
                          {visibleCampaigns.length > 10 && (
                            <div className="text-jarvis-muted text-xs pt-0.5">
                              +{visibleCampaigns.length - 10} more
                              {lcFilter && ` matching "${campaignFilter}"`}
                            </div>
                          )}
                        </div>
                      )}

                      {visibleCampaigns.length === 0 && profile.campaigns.length > 0 && lcFilter && (
                        <div className="text-jarvis-muted text-xs border-t border-jarvis-border/50 pt-2 mt-2">
                          No campaigns matching &ldquo;{campaignFilter}&rdquo;
                        </div>
                      )}

                      {profile.campaigns.length === 0 && !profile.error && (
                        <div className="text-jarvis-muted text-xs">No campaigns captured</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </>
      )}

      {/* ── Command pending note ── */}
      <div className="mt-2 text-jarvis-muted text-xs text-center">
        Campaign toggles execute on next scraper run (~5 min) · JARVIS notifies on completion
      </div>

      {/* ── Campaign Insights ── */}
      <CampaignInsightsPanel hermes={HERMES} />

      {/* ── Budget & Alert Config ── */}
      <BudgetConfigPanel hermes={HERMES} />
    </div>
  );
}
