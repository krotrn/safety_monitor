import { IconActivity } from "@tabler/icons-react";
import { HeatmapPoint } from "../../types/dashboard";

interface ProximityRadarProps {
  points: HeatmapPoint[];
}

export const ProximityRadar = ({ points }: ProximityRadarProps) => {
  return (
    <section className="bg-gradient-to-br from-blue-900/10 to-indigo-900/10 border border-blue-500/20 rounded-3xl p-6 backdrop-blur-sm">
      <h3 className="text-lg font-medium text-blue-200 flex items-center gap-2 mb-4">
        <IconActivity className="w-5 h-5" />
        Near-Miss Proximity Radar
      </h3>
      <div className="aspect-square bg-black/40 rounded-2xl border border-blue-500/20 relative overflow-hidden flex items-center justify-center">
        <div className="absolute inset-0 bg-[conic-gradient(from_0deg,transparent_0_340deg,rgba(59,130,246,0.3)_360deg)] animate-[spin_4s_linear_infinite]" />
        <div className="absolute inset-0 border border-blue-500/20 rounded-full w-1/3 h-1/3 m-auto" />
        <div className="absolute inset-0 border border-blue-500/20 rounded-full w-2/3 h-2/3 m-auto" />
        
        {points.map((pt, i) => (
          <div 
            key={i} 
            className="absolute w-2 h-2 bg-rose-500 rounded-full shadow-[0_0_10px_rgba(244,63,94,1)] animate-pulse"
            style={{ left: `${pt.x * 100}%`, top: `${pt.y * 100}%`, transform: 'translate(-50%, -50%)' }}
          />
        ))}

        <span className="relative z-10 text-xs font-mono text-blue-400 bg-black/50 px-2 py-1 rounded">
          MONITORING ZONES
        </span>
      </div>
    </section>
  );
};
