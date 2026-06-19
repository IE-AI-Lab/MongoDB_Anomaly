"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

import { MongoLeaf } from "./Logo";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/chat", label: "Chatbot" },
  { href: "/feedback", label: "Feedback" },
  { href: "/knowledge", label: "Knowledge Base" },
];

export function TopBar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-40 bg-mongo-header text-white">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-5 px-5">
        <Link href="/" className="flex items-center gap-2">
          <MongoLeaf className="h-6 w-6" color="#00ED64" />
          <span className="text-base font-semibold tracking-tight">MongoDB Agent</span>
        </Link>

        <nav className="flex items-center gap-0.5">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm transition-colors",
                isActive(item.href)
                  ? "bg-white/10 font-medium text-white"
                  : "text-white/60 hover:bg-white/5 hover:text-white"
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="hidden text-xs text-white/45 lg:inline">
            MongoDB Atlas · CNC Anomaly Detection
          </span>
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-mongo-purple text-xs font-semibold text-white">
              M
            </span>
            <span className="hidden text-sm font-medium text-white sm:inline">
              Manager
            </span>
          </div>
          <button
            type="button"
            className="rounded-md border border-white/25 px-2.5 py-1 text-xs text-white/85 transition-colors hover:bg-white/10"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
