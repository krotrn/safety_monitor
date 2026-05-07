import { IconVideo, IconCamera, IconActivity } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { dashboardService } from "../../services/api";

export const VideoFeed = () => {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium flex items-center gap-2">
          <IconVideo className="w-5 h-5 text-neutral-400" />
          Live Feeds
        </h2>
        <div className="text-xs px-2 py-1 bg-white/10 rounded border border-white/5 text-neutral-300 font-mono">
          MJPEG / 30 FPS
        </div>
      </div>
      
      <div className="relative group overflow-hidden rounded-3xl border border-white/10 bg-black/50 aspect-video shadow-2xl">
        <div className="absolute inset-0 flex items-center justify-center text-neutral-600 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-neutral-900 to-black">
          <div className="flex flex-col items-center gap-2">
            <IconCamera className="w-12 h-12 opacity-50" />
            <span className="text-sm font-medium tracking-widest opacity-50">CONNECTING...</span>
          </div>
        </div>

        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img 
          src={dashboardService.getFeedUrl()}
          alt="Live Camera Feed"
          className="absolute inset-0 w-full h-full object-cover z-10 transition-opacity duration-500"
          onError={(e) => {
            (e.target as HTMLImageElement).style.opacity = '0';
          }}
          onLoad={(e) => {
            (e.target as HTMLImageElement).style.opacity = '1';
          }}
        />

        <div className="absolute top-4 left-4 z-20 flex items-center gap-2 px-3 py-1.5 bg-black/60 backdrop-blur-md rounded-lg border border-white/10">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <span className="text-xs font-mono font-medium text-white tracking-wider">CAM_01</span>
        </div>
        
        <div className="absolute bottom-4 left-4 right-4 z-20 flex justify-between items-end">
          <div suppressHydrationWarning className="px-3 py-1.5 bg-black/60 backdrop-blur-md rounded-lg border border-white/10 text-xs font-mono text-neutral-300">
            {time.toISOString().split('T')[0]} {time.toLocaleTimeString()}
          </div>
          <div className="px-3 py-1.5 bg-black/60 backdrop-blur-md rounded-lg border border-white/10 text-xs font-mono text-emerald-400 flex items-center gap-2">
            <IconActivity className="w-4 h-4" />
            ANALYZING
          </div>
        </div>
      </div>
    </section>
  );
};
