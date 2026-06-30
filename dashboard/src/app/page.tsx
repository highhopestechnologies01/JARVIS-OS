import { Suspense } from "react";
import { BriefingPanel } from "@/components/panels/BriefingPanel";
import { InfraPanel } from "@/components/panels/InfraPanel";
import { MemoryPanel } from "@/components/panels/MemoryPanel";
import { NotificationsPanel } from "@/components/panels/NotificationsPanel";
import { SchedulerPanel } from "@/components/panels/SchedulerPanel";
import { VoicePanel } from "@/components/panels/VoicePanel";
import { IntelligencePanel } from "@/components/panels/IntelligencePanel";
import { CoolifyPanel } from "@/components/panels/CoolifyPanel";
import { RDPPanel } from "@/components/panels/RDPPanel";
import { MetaAdsPanel } from "@/components/panels/MetaAdsPanel";
import { Header } from "@/components/layout/Header";

export const dynamic = "force-dynamic";
export const revalidate = 30;

export default function Dashboard() {
  return (
    <div className="min-h-screen bg-jarvis-bg">
      <Header />

      <main className="p-4 lg:p-6 grid grid-cols-12 gap-4 max-w-[1800px] mx-auto">
        {/* Meta Ads — full width, primary panel */}
        <div className="col-span-12">
          <MetaAdsPanel />
        </div>

        {/* Top row: Briefing (wide) + Infra (narrow) */}
        <div className="col-span-12 lg:col-span-8">
          <Suspense fallback={<PanelSkeleton title="Today's Briefing" />}>
            <BriefingPanel />
          </Suspense>
        </div>

        <div className="col-span-12 lg:col-span-4">
          <Suspense fallback={<PanelSkeleton title="Infrastructure" />}>
            <InfraPanel />
          </Suspense>
        </div>

        {/* Bottom row: Memory + Scheduler + Notifications */}
        <div className="col-span-12 lg:col-span-5">
          <Suspense fallback={<PanelSkeleton title="Memory" />}>
            <MemoryPanel />
          </Suspense>
        </div>

        <div className="col-span-12 lg:col-span-4">
          <Suspense fallback={<PanelSkeleton title="Scheduler" />}>
            <SchedulerPanel />
          </Suspense>
        </div>

        <div className="col-span-12 lg:col-span-3">
          <Suspense fallback={<PanelSkeleton title="Notifications" />}>
            <NotificationsPanel />
          </Suspense>
        </div>

        {/* Intelligence + Deployments + Voice row */}
        <div className="col-span-12 lg:col-span-8">
          <IntelligencePanel />
        </div>

        <div className="col-span-12 lg:col-span-4 flex flex-col gap-4">
          <RDPPanel />
          <CoolifyPanel />
          <VoicePanel />
        </div>
      </main>
    </div>
  );
}

function PanelSkeleton({ title }: { title: string }) {
  return (
    <div className="bg-jarvis-surface border border-jarvis-border rounded-xl p-4 h-48 animate-pulse">
      <div className="text-jarvis-muted text-sm">{title}</div>
    </div>
  );
}
