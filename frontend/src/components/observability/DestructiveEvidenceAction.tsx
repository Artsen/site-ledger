import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Trash2, X } from "lucide-react";
import { ReactNode, useEffect, useId, useRef, useState } from "react";

import { Button } from "../ui/Button";
import { ErrorBanner } from "../ui/ErrorBanner";
import { LoadingBlock } from "../ui/Loading";

type Preview = { can_delete: boolean; reason: string | null };
type Result = { warnings: string[] };

type Props<TPreview extends Preview, TResult extends Result> = {
  label: string;
  title: string;
  description: string;
  queryKey: readonly unknown[];
  loadPreview: () => Promise<TPreview>;
  deleteEvidence: (confirmation: string) => Promise<TResult>;
  confirmationPhrase?: string;
  renderPreview: (preview: TPreview) => ReactNode;
  onDeleted: (result: TResult) => void | Promise<void>;
  className?: string;
};

export function DestructiveEvidenceAction<TPreview extends Preview, TResult extends Result>({
  label,
  title,
  description,
  queryKey,
  loadPreview,
  deleteEvidence,
  confirmationPhrase,
  renderPreview,
  onDeleted,
  className,
}: Props<TPreview, TResult>) {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const preview = useQuery({ queryKey, queryFn: loadPreview, enabled: open, staleTime: 0 });
  const remove = useMutation({
    mutationFn: () => deleteEvidence(confirmation),
    onSuccess: async (result) => {
      await onDeleted(result);
      setOpen(false);
      setConfirmation("");
    },
  });

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const trigger = triggerRef.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])') ?? []);
    focusable()[0]?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !remove.isPending) {
        event.preventDefault();
        setOpen(false);
        return;
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
    dialog?.addEventListener("keydown", handleKeyDown);
    return () => {
      dialog?.removeEventListener("keydown", handleKeyDown);
      trigger?.focus();
    };
  }, [open, remove.isPending]);

  const phraseMatches = !confirmationPhrase || confirmation === confirmationPhrase;
  const canDelete = Boolean(preview.data?.can_delete && phraseMatches && !remove.isPending);
  return <>
    <Button ref={triggerRef} type="button" variant="danger" className={className} onClick={() => setOpen(true)}><Trash2 size={16} className="mr-2" />{label}</Button>
    {open ? <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} className="fixed inset-0 z-50 overflow-y-auto bg-black/40 p-3 sm:p-8">
      <div className="mx-auto max-w-xl rounded-md bg-white p-4 shadow-xl sm:p-6">
        <header className="flex items-start justify-between gap-3">
          <div><h2 id={titleId} className="flex items-center gap-2 text-lg font-semibold text-red-800"><AlertTriangle size={20} />{title}</h2><p id={descriptionId} className="mt-1 text-sm text-stone-600">{description}</p></div>
          <button type="button" aria-label="Close deletion dialog" disabled={remove.isPending} onClick={() => setOpen(false)} className="rounded p-2 hover:bg-stone-100 disabled:opacity-60"><X size={20} /></button>
        </header>
        <div className="mt-5 border-y border-stone-200 py-4">
          {preview.isLoading ? <LoadingBlock label="Calculating deletion impact..." /> : null}
          {preview.error ? <ErrorBanner error={preview.error} title="Could not calculate deletion impact" /> : null}
          {preview.data ? renderPreview(preview.data) : null}
          {preview.data && !preview.data.can_delete ? <p className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"><strong>Deletion unavailable.</strong> {preview.data.reason ?? "The current evidence state does not allow deletion."}</p> : null}
        </div>
        {confirmationPhrase ? <label className="mt-4 block text-sm"><span className="font-medium">Type <code>{confirmationPhrase}</code> to confirm</span><input className="mt-2 w-full rounded-md border border-stone-300 px-3 py-2 font-mono" value={confirmation} autoComplete="off" onChange={(event) => setConfirmation(event.target.value)} /></label> : null}
        {remove.error ? <div className="mt-4"><ErrorBanner error={remove.error} title="Could not delete evidence" /></div> : null}
        <div className="mt-5 flex justify-end gap-2"><Button type="button" disabled={remove.isPending} onClick={() => setOpen(false)}>Cancel</Button><Button type="button" variant="danger" loading={remove.isPending} disabled={!canDelete} onClick={() => remove.mutate()}>Delete permanently</Button></div>
      </div>
    </section> : null}
  </>;
}

export function DeletionImpact({ items }: { items: Array<{ label: string; value: ReactNode }> }) {
  return <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">{items.map((item) => <div key={item.label}><dt className="text-stone-600">{item.label}</dt><dd className="font-medium tabular-nums">{item.value}</dd></div>)}</dl>;
}
