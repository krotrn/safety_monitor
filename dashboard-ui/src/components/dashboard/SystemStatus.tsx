import { IconChartBar } from "@tabler/icons-react";
import { Stats, Incident } from "../../types/dashboard";

interface SystemStatusProps {
  stats: Stats | undefined;
  incidents: Incident[];
}

export const SystemStatus = ({ stats, incidents }: SystemStatusProps) => {
  const criticalCount = incidents.filter(i => i.action_tier === 'alert').length;

  return (
    <section>
      <h2 className="text-xl font-medium mb-4 flex items-center gap-2 text-white">
        <IconChartBar className="w-5 h-5 text-neutral-400" />
        System Status
      </h2>
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white/5 border border-white/10 rounded-2xl p-5 flex flex-col gap-1 backdrop-blur-sm hover:bg-white/10 transition-colors">
          <span className="text-sm font-medium text-neutral-400">Total Events (24h)</span>
          <span className="text-3xl font-semibold text-white">
            {stats?.total_incidents || 0}
          </span>
        </div>
        <div className="bg-white/5 border border-white/10 rounded-2xl p-5 flex flex-col gap-1 backdrop-blur-sm hover:bg-white/10 transition-colors">
          <span className="text-sm font-medium text-neutral-400">Critical Alerts</span>
          <span className="text-3xl font-semibold text-rose-400">
            {criticalCount}
          </span>
        </div>
      </div>
    </section>
  );
};
