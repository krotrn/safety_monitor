import { IconShieldCheck } from "@tabler/icons-react";

export const Header = () => {
  return (
    <header className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pb-6 border-b border-white/10">
      <div className="flex items-center gap-4">
        <div className="p-3 bg-white/5 rounded-2xl border border-white/10 shadow-[0_0_15px_rgba(255,255,255,0.05)]">
          <IconShieldCheck className="w-8 h-8 text-emerald-400" />
        </div>
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-white">SafeGrid Monitor</h1>
          <p className="text-neutral-400 text-sm mt-1">Real-time Safety Intelligence & Edge Analytics</p>
        </div>
      </div>
      <div className="flex items-center gap-3 bg-white/5 px-4 py-2 rounded-full border border-white/10">
        <span className="relative flex h-3 w-3">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
        </span>
        <span className="text-sm font-medium tracking-wide text-emerald-400">SYSTEM ONLINE</span>
      </div>
    </header>
  );
};
