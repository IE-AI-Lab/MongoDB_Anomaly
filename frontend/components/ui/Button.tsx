"use client";

import clsx from "clsx";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-mongo-green-base text-mongo-green-darker hover:bg-[#00D95B] border border-transparent font-semibold",
  secondary:
    "bg-white text-mongo-ink border border-mongo-border hover:border-mongo-mist",
  danger:
    "bg-white text-severity-highInk border border-severity-high hover:bg-severity-high/30",
  ghost: "bg-transparent text-mongo-green-dark hover:bg-mongo-green-tint border border-transparent",
};

const SIZES: Record<Size, string> = {
  sm: "px-2.5 py-1 text-xs rounded-md",
  md: "px-4 py-2 text-sm rounded-lg",
};

// Shared so a Next <Link> can look like a button without nesting <button> in <a>.
export function buttonClasses(
  variant: Variant = "secondary",
  size: Size = "md",
  className?: string
) {
  return clsx(
    "inline-flex items-center justify-center gap-1.5 transition-colors",
    "focus:outline-none focus-visible:ring-2 focus-visible:ring-mongo-green-dark/40",
    "disabled:opacity-50 disabled:cursor-not-allowed",
    VARIANTS[variant],
    SIZES[size],
    className
  );
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({
  variant = "secondary",
  size = "md",
  className,
  disabled,
  ...rest
}: Props) {
  return (
    <button {...rest} disabled={disabled} className={buttonClasses(variant, size, className)} />
  );
}
