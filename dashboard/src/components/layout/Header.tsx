import { format } from "date-fns";

export function Header() {
  const now = new Date();

  return (
    <header className="border-b border-jarvis-border bg-jarvis-surface/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-[1800px] mx-auto px-4 lg:px-6 py-3 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-jarvis-accent flex items-center justify-center text-white font-bold text-sm">
            J
          </div>
          <div>
            <div className="text-jarvis-text font-semibold text-sm tracking-wide">JARVIS OS</div>
            <div className="text-jarvis-muted text-xs">Executive Dashboard</div>
          </div>
        </div>

        {/* Center: Live indicator */}
        <div className="flex items-center gap-2 text-jarvis-muted text-xs">
          <div className="w-2 h-2 rounded-full bg-jarvis-green status-live" />
          <span>LIVE</span>
        </div>

        {/* Right: Date/time */}
        <div className="text-right">
          <div className="text-jarvis-text text-sm font-mono">
            {format(now, "EEEE, MMM d")}
          </div>
          <div className="text-jarvis-muted text-xs font-mono">
            {format(now, "HH:mm")} ET
          </div>
        </div>
      </div>
    </header>
  );
}
