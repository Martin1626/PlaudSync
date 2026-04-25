import { NavLink } from "react-router-dom";

import type { SyncState } from "@/api/types";
import { classNames } from "@/utils/format";

import Logo from "./Logo";
import SyncStatusBadge from "./SyncStatusBadge";

interface Props {
  sync: SyncState;
}

export default function Header({ sync }: Props) {
  return (
    <header className="sticky top-0 z-30 bg-white/90 backdrop-blur border-b border-gray-200">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-6">
        <Logo />
        <nav className="flex items-center gap-1 ml-2">
          <NavTab to="/" label="Přehled" />
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
}

function NavTab({ to, label }: NavTabProps) {
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
          {isActive && (
            <span className="absolute -bottom-[13px] left-2 right-2 h-0.5 bg-blue-600 rounded-full" />
          )}
        </>
      )}
    </NavLink>
  );
}
