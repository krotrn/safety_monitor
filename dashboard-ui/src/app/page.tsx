"use client";

import { Header } from "../components/dashboard/Header";
import { LiveAlerts } from "../components/dashboard/LiveAlerts";
import { VideoFeed } from "../components/dashboard/VideoFeed";
import { SystemStatus } from "../components/dashboard/SystemStatus";
import { ProximityRadar } from "../components/dashboard/ProximityRadar";
import { IncidentLog } from "../components/dashboard/IncidentLog";
import { useDashboardData, useDashboardActions } from "../hooks/useDashboardData";
import { useDashboardWebSocket } from "../hooks/useDashboardWebSocket";

export default function Dashboard() {
  const { incidents, stats, heatmapPoints } = useDashboardData();
  const { acknowledge, markFalsePositive, isAckPending, isFpPending } = useDashboardActions();
  const { liveAlerts, removeAlert } = useDashboardWebSocket();

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 p-4 md:p-8 font-sans selection:bg-rose-500/30">
      
      <div className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-blue-900/20 blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-rose-900/20 blur-[120px]" />
      </div>

      <main className="relative z-10 max-w-7xl mx-auto space-y-8">
        
        <Header />

        <LiveAlerts alerts={liveAlerts} onRemove={removeAlert} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          
          <div className="lg:col-span-2 space-y-8">
            <VideoFeed />
          </div>

          <div className="space-y-8">
            <SystemStatus stats={stats} incidents={incidents} />
            <ProximityRadar points={heatmapPoints} />
          </div>
        </div>

        <IncidentLog 
          incidents={incidents}
          onAcknowledge={acknowledge}
          onFalsePositive={markFalsePositive}
          isAckPending={isAckPending}
          isFpPending={isFpPending}
        />

      </main>
    </div>
  );
}
