import { ArchiveRestore, EyeOff, Trash2, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";

type Props = {
  label: string;
  title: string;
  description: string;
  confirmLabel: string;
  action: () => Promise<unknown>;
  restore?: boolean;
  variant?: "secondary" | "danger";
  className?: string;
};

export function LifecycleAction({
  label,
  title,
  description,
  confirmLabel,
  action,
  restore = false,
  variant = "secondary",
  className,
}: Props) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const Icon = restore ? ArchiveRestore : variant === "danger" ? Trash2 : EyeOff;

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const trigger = triggerRef.current;
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
    focusable()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !pending) {
        event.preventDefault();
        setOpen(false);
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog?.addEventListener("keydown", onKeyDown);
    return () => {
      dialog?.removeEventListener("keydown", onKeyDown);
      trigger?.focus();
    };
  }, [open, pending]);

  const confirm = async () => {
    setPending(true);
    setError(undefined);
    try {
      await action();
      setOpen(false);
    } catch (caught) {
      setError(caught);
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <Button
        ref={triggerRef}
        type="button"
        variant={variant}
        className={className}
        onClick={() => setOpen(true)}
      >
        <Icon size={16} className="mr-2" />
        {label}
      </Button>
      {open ? (
        <section
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          className="fixed inset-0 z-50 overflow-y-auto bg-black/40 p-3 sm:p-8"
        >
          <div className="mx-auto max-w-lg rounded-md bg-white p-4 shadow-xl sm:p-6">
            <header className="flex items-start justify-between gap-3">
              <div>
                <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
                <p id={descriptionId} className="mt-1 text-sm text-stone-600">{description}</p>
              </div>
              <button
                type="button"
                aria-label="Close confirmation"
                disabled={pending}
                onClick={() => setOpen(false)}
                className="rounded p-2 hover:bg-stone-100 disabled:opacity-60"
              >
                <X size={20} />
              </button>
            </header>
            {error ? <div className="mt-4"><ErrorBanner error={error} title="Could not update state" /></div> : null}
            <div className="mt-5 flex justify-end gap-2 border-t border-stone-200 pt-4">
              <Button type="button" disabled={pending} onClick={() => setOpen(false)}>Cancel</Button>
              <Button type="button" variant={variant} loading={pending} onClick={confirm}>{confirmLabel}</Button>
            </div>
          </div>
        </section>
      ) : null}
    </>
  );
}
