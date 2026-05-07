import { IconListDetails, IconCheck, IconX } from "@tabler/icons-react";
import { Incident } from "../../types/dashboard";

interface IncidentLogProps {
  incidents: Incident[];
  onAcknowledge: (id: string) => void;
  onFalsePositive: (id: string) => void;
  isAckPending: boolean;
  isFpPending: boolean;
}

export const IncidentLog = ({ 
  incidents, 
  onAcknowledge, 
  onFalsePositive,
  isAckPending,
  isFpPending
}: IncidentLogProps) => {
  return (
    <section className="bg-white/5 border border-white/10 rounded-3xl p-6 backdrop-blur-sm overflow-hidden flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium flex items-center gap-2 text-white">
          <IconListDetails className="w-5 h-5 text-neutral-400" />
          Incident Log
        </h2>
        <div className="text-sm text-neutral-400">
          Showing last {incidents.length} events
        </div>
      </div>
      
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm text-neutral-300">
          <thead className="text-xs uppercase bg-black/20 text-neutral-500 border-b border-white/10">
            <tr>
              <th className="px-4 py-3 font-medium rounded-tl-lg">Time</th>
              <th className="px-4 py-3 font-medium">Type</th>
              <th className="px-4 py-3 font-medium">Score</th>
              <th className="px-4 py-3 font-medium">Camera</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium text-right rounded-tr-lg">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {incidents.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-neutral-500">
                  No incidents recorded yet.
                </td>
              </tr>
            ) : (
              incidents.map((incident) => (
                <tr 
                  key={incident.id} 
                  className={`hover:bg-white/[0.02] transition-colors ${
                    incident.action_tier === 'alert' ? 'bg-rose-500/[0.02]' : ''
                  }`}
                >
                  <td className="px-4 py-3 whitespace-nowrap font-mono text-xs">
                    {new Date(incident.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </td>
                  <td className="px-4 py-3 font-medium text-white">
                    {incident.event_type}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      incident.severity_score >= 80 ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' :
                      incident.severity_score >= 50 ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' :
                      'bg-neutral-500/20 text-neutral-300 border border-neutral-500/30'
                    }`}>
                      {incident.severity_score.toFixed(0)}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs opacity-70">
                    {incident.camera_id || incident.source_id}
                  </td>
                  <td className="px-4 py-3">
                    {incident.false_positive ? (
                      <span className="text-neutral-500 line-through text-xs">Ignored</span>
                    ) : incident.acknowledged ? (
                      <span className="text-emerald-400 flex items-center gap-1 text-xs">
                        <IconCheck className="w-3 h-3" /> Ack&apos;d
                      </span>
                    ) : (
                      <span className="text-amber-400 flex items-center gap-1 text-xs animate-pulse">
                        <div className="w-1.5 h-1.5 rounded-full bg-amber-400" /> Pending
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button 
                        onClick={() => onAcknowledge(incident.id)}
                        disabled={incident.acknowledged || incident.false_positive || isAckPending}
                        className="p-1.5 rounded-md text-emerald-400 hover:bg-emerald-400/20 disabled:opacity-30 disabled:hover:bg-transparent transition-colors cursor-pointer"
                        title="Acknowledge"
                      >
                        <IconCheck className="w-4 h-4" />
                      </button>
                      <button 
                        onClick={() => onFalsePositive(incident.id)}
                        disabled={incident.acknowledged || incident.false_positive || isFpPending}
                        className="p-1.5 rounded-md text-rose-400 hover:bg-rose-400/20 disabled:opacity-30 disabled:hover:bg-transparent transition-colors cursor-pointer"
                        title="Mark False Positive"
                      >
                        <IconX className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
