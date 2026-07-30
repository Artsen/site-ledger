import { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  loading?: boolean;
  children: ReactNode;
};

export function Button({ variant = "secondary", loading = false, children, className = "", disabled, ...props }: ButtonProps) {
  const variants = {
    primary: "border-neutral-900 bg-neutral-900 text-white hover:bg-neutral-700",
    secondary: "border-stone-300 bg-white text-stone-900 hover:bg-stone-50",
    ghost: "border-transparent bg-transparent text-stone-700 hover:bg-stone-100",
    danger: "border-red-300 bg-white text-red-700 hover:bg-red-50"
  };
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={`inline-flex min-h-9 items-center justify-center rounded-md border px-3 py-2 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
