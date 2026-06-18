"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Briefcase, Search, UserCircle, Zap } from "lucide-react";

const links = [
  { href: "/", label: "Command Center", icon: Zap, exact: true },
  { href: "/roles", label: "Role Inbox", icon: Briefcase, exact: false },
  { href: "/search", label: "Search", icon: Search, exact: false },
  { href: "/profile", label: "Profile", icon: UserCircle, exact: false },
];

export function Nav() {
  const path = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 w-56 flex flex-col"
           style={{ background: "var(--sidebar-background)", color: "var(--sidebar-foreground)" }}>
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 py-5 border-b border-white/10">
        <span className="text-2xl">🦞</span>
        <div>
          <div className="font-bold text-sm tracking-wide text-white">OpenClaw</div>
          <div className="text-xs opacity-50">Career Intelligence</div>
        </div>
      </div>

      {/* Nav links */}
      <nav className="flex-1 py-4 px-3 space-y-1">
        {links.map(({ href, label, icon: Icon, exact }) => {
          const active = exact ? path === href : path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors
                ${active
                  ? "bg-white/15 text-white font-medium"
                  : "text-white/60 hover:text-white hover:bg-white/10"}`}
            >
              <Icon size={16} />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-white/10">
        <div className="text-xs text-white/30">Career Intelligence Workspace</div>
      </div>
    </aside>
  );
}
