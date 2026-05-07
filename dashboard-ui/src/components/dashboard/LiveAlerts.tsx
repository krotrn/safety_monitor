import { IconAlertTriangle, IconX } from "@tabler/icons-react";
import { Incident } from "../../types/dashboard";

interface LiveAlertsProps {
  alerts: Incident[];
  onRemove: (id: string) => void;
}

export const LiveAlerts = ({ alerts, onRemove }: LiveAlertsProps) => {
  if (alerts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-50 w-full max-w-md flex flex-col gap-3 pointer-events-none">
      {alerts.map((alert, idx) => (
        <div 
          key={`${alert.timestamp}-${idx}`}
          className={`pointer-events-auto animate-in fade-in slide-in-from-top-4 flex items-center justify-between p-4 rounded-2xl border backdrop-blur-md shadow-2xl ${
            alert.action_tier === 'alert' 
              ? 'bg-rose-950/80 border-rose-500/50 text-rose-200 shadow-rose-500/20' 
              : 'bg-amber-950/80 border-amber-500/50 text-amber-200 shadow-amber-500/20'
          }`}
        >
          <div className="flex items-center gap-4">
            <div className={`p-2 rounded-full ${alert.action_tier === 'alert' ? 'bg-rose-500/20' : 'bg-amber-500/20'}`}>
              <IconAlertTriangle className={`w-6 h-6 ${alert.action_tier === 'alert' ? 'text-rose-400' : 'text-amber-400'}`} />
            </div>
            <div>
              <h3 className="font-semibold text-lg">{alert.event_type} Detected</h3>
              <p className="text-sm opacity-80">
                Camera: {alert.source_id} • Score: {alert.severity_score.toFixed(1)}/100
              </p>
            </div>
          </div>
          <button 
            className="p-2 opacity-60 hover:opacity-100 transition-opacity cursor-pointer"
            onClick={() => onRemove(alert.alertId || alert.id)}
          >
            <IconX className="w-5 h-5" />
          </button>
        </div>
      ))}
    </div>
  );
};
