import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { deleteNote, updateNote } from "../api/client";
import type { Note, NoteList } from "../types/scans";
import { formatDate } from "../utils/format";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { ErrorBanner } from "./ui/ErrorBanner";
import { LoadingBlock } from "./ui/Loading";

type NotesPanelProps = {
  queryKey: readonly unknown[];
  list: (query: string) => Promise<NoteList>;
  create: (body: string, isPinned: boolean) => Promise<Note>;
  context: string;
};

export function NotesPanel({
  queryKey,
  list,
  create,
  context,
}: NotesPanelProps) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const search = searchParams.get("notes_search") ?? "";
  const offset = Number(searchParams.get("notes_offset") ?? "0");
  const [body, setBody] = useState("");
  const [pinned, setPinned] = useState(false);
  const notes = useQuery({
    queryKey: [...queryKey, search, offset],
    queryFn: () =>
      list(
        `?limit=25&offset=${offset}${
          search ? `&search=${encodeURIComponent(search)}` : ""
        }`,
      ),
  });
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: [...queryKey] });
  const add = useMutation({
    mutationFn: () => create(body, pinned),
    onSuccess: async () => {
      setBody("");
      setPinned(false);
      await refresh();
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (body.trim()) add.mutate();
  };
  return (
    <div className="space-y-4">
      <form
        onSubmit={submit}
        className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"
      >
        <label htmlFor="note-body" className="mb-2 block text-sm font-medium">
          Add note for {context}
        </label>
        <textarea
          id="note-body"
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={4}
          maxLength={20000}
          className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={pinned}
              onChange={(event) => setPinned(event.target.checked)}
            />{" "}
            Pin note
          </label>
          <Button type="submit" loading={add.isPending} disabled={!body.trim()}>
            Add note
          </Button>
        </div>
      </form>
      <div className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <label htmlFor="note-search" className="sr-only">
          Search notes
        </label>
        <input
          id="note-search"
          value={search}
          onChange={(event) =>
            setSearchParams((current) => {
              const next = new URLSearchParams(current);
              if (event.target.value) {
                next.set("notes_search", event.target.value);
              } else {
                next.delete("notes_search");
              }
              next.delete("notes_offset");
              return next;
            })
          }
          placeholder="Search notes"
          className="mb-4 w-full max-w-md rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
        {notes.error || add.error ? (
          <ErrorBanner
            error={notes.error ?? add.error}
            title="Note action failed"
          />
        ) : null}
        {notes.isLoading ? <LoadingBlock label="Loading notes..." /> : null}
        {notes.data?.items.length ? (
          <div className="space-y-3">
            {notes.data.items.map((note) => (
              <NoteCard key={note.id} note={note} refresh={refresh} />
            ))}
          </div>
        ) : !notes.isLoading ? (
          <EmptyState
            title="No notes"
            message={`No notes have been added for ${context}.`}
          />
        ) : null}
        {notes.data ? (
          <div className="mt-4 flex items-center justify-between gap-3 text-sm">
            <span>{notes.data.total} notes</span>
            <div className="flex gap-2">
              <Button
                type="button"
                disabled={notes.data.offset <= 0}
                onClick={() =>
                  setSearchParams((current) => {
                    const next = new URLSearchParams(current);
                    next.set(
                      "notes_offset",
                      String(Math.max(0, notes.data.offset - notes.data.limit)),
                    );
                    return next;
                  })
                }
              >
                Previous
              </Button>
              <Button
                type="button"
                disabled={
                  notes.data.offset + notes.data.limit >= notes.data.total
                }
                onClick={() =>
                  setSearchParams((current) => {
                    const next = new URLSearchParams(current);
                    next.set(
                      "notes_offset",
                      String(notes.data.offset + notes.data.limit),
                    );
                    return next;
                  })
                }
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function NoteCard({
  note,
  refresh,
}: {
  note: Note;
  refresh: () => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(note.body);
  const update = useMutation({
    mutationFn: (payload: { body?: string; is_pinned?: boolean }) =>
      updateNote(note.id, payload),
    onSuccess: async () => {
      setEditing(false);
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteNote(note.id),
    onSuccess: refresh,
  });
  return (
    <article className="rounded-md border border-stone-200 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-stone-500">
        <span>
          {note.is_pinned ? "Pinned note" : "Note"} - updated{" "}
          {formatDate(note.updated_at)}
        </span>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => update.mutate({ is_pinned: !note.is_pinned })}
          >
            {note.is_pinned ? "Unpin" : "Pin"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setEditing((value) => !value)}
          >
            Edit
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={() => {
              if (window.confirm("Delete this note? This cannot be undone."))
                remove.mutate();
            }}
          >
            Delete
          </Button>
        </div>
      </div>
      {editing ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (body.trim()) update.mutate({ body });
          }}
        >
          <label htmlFor={`note-${note.id}`} className="sr-only">
            Edit note
          </label>
          <textarea
            id={`note-${note.id}`}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={4}
            className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm"
          />
          <Button
            type="submit"
            loading={update.isPending}
            disabled={!body.trim()}
          >
            Save note
          </Button>
        </form>
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm">{note.body}</p>
      )}
      {update.error || remove.error ? (
        <ErrorBanner
          error={update.error ?? remove.error}
          title="Note action failed"
        />
      ) : null}
    </article>
  );
}
