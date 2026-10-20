import { NavLink } from "react-router-dom";

import { useSpeakersQuery } from "@/api/hooks";
import type { SyncState } from "@/api/types";
import { classNames } from "@/utils/format";

import Logo from "./Logo";
import SyncStatusBadge from "./SyncStatusBadge";

interface Props {
  sync: SyncState;
}

export default function Header({ sync }: Props) {
  const pending = useSpeakersQuery("flagged").data?.pending_count ?? 0;
  return (
    <header className="sticky top-0 z-30 bg-white/90 backdrop-blur border-b border-gray-200">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-6">
        <Logo />
        <nav className="flex items-center gap-1 ml-2">
          <NavTab to="/" label="Přehled" />
          <NavTab to="/speakers" label="Řečníci" count={pending} />
          <NavTab to="/settings" label="Nastavení" />
        </nav>
        <div className="ml-auto">
          <SyncStatusBadge sync={sync} />
        </div>
      </div>
    </header>
  );
}

interface NavTabProps {
  to: string;
  label: string;
  count?: number;
}

function NavTab({ to, label, count }: NavTabProps) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        classNames(
          "relative px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
          isActive
            ? "text-gray-900 bg-gray-100"
            : "text-gray-600 hover:text-gray-900 hover:bg-gray-50",
        )
      }
    >
      {({ isActive }) => (
        <>
          {label}
          {count !== undefined && count > 0 && (
            <span className="ml-1.5 inline-flex items-center justify-center min-w-5 px-1.5 text-xs font-semibold rounded-full bg-blue-600 text-white">
              {count}
            </span>
          )}
          {isActive && (
            <span className="absolute -bottom-[13px] left-2 right-2 h-0.5 bg-blue-600 rounded-full" />
          )}
        </>
      )}
    </NavLink>
  );
}
