// Small design-system primitives shared by every screen.
"use client";

import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useId, useState, type ButtonHTMLAttributes, type ReactNode } from "react";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={clsx("rounded-xl border border-zinc-200 bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]", className)}>
      {children}
    </div>
  );
}

type Tone = "neutral" | "brand" | "good" | "warn" | "bad";

const TONES: Record<Tone, string> = {
  neutral: "bg-zinc-100 text-zinc-700 ring-zinc-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-100",
  good: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  warn: "bg-amber-50 text-amber-800 ring-amber-100",
  bad: "bg-rose-50 text-rose-700 ring-rose-100",
};

export function Badge({ tone = "neutral", icon, children }: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone])}>
      {icon}
      {children}
    </span>
  );
}

type Variant = "primary" | "secondary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm disabled:bg-zinc-300",
  secondary: "bg-white text-zinc-800 ring-1 ring-inset ring-zinc-200 hover:bg-zinc-50 disabled:text-zinc-400",
  ghost: "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 disabled:text-zinc-300",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      type="button"
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-zinc-200 px-5">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={clsx(
            "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
            value === t.id ? "border-brand-600 text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-800",
          )}
        >
          {t.label}
          {t.count !== undefined && (
            <span className="rounded-full bg-zinc-100 px-1.5 text-[11px] font-semibold text-zinc-600">{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Disclosure({
  title,
  defaultOpen = false,
  children,
}: {
  title: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs font-medium text-zinc-500 hover:text-zinc-800"
      >
        <ChevronDown className={clsx("size-3.5 transition-transform", !open && "-rotate-90")} />
        {title}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{children}</h3>
      {aside}
    </div>
  );
}

export function Callout({ tone, icon, children }: { tone: "info" | "warn" | "error"; icon?: ReactNode; children: ReactNode }) {
  const styles = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    warn: "border-amber-200 bg-amber-50 text-amber-900",
    error: "border-rose-200 bg-rose-50 text-rose-900",
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={clsx("flex gap-2.5 rounded-lg border px-3.5 py-2.5 text-sm", styles)}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Logo({ className }: { className?: string }) {
  // Unique per instance: a gradient defined inside a hidden copy would not paint the others.
  const id = useId();
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#818cf8" />
          <stop offset="1" stopColor="#4f46e5" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${id})`} />
      <path d="M8 21l5-6 4 3.5L24 10" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="24" cy="10" r="2.2" fill="#fff" />
    </svg>
  );
}
