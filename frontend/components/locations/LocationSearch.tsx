"use client";

import { LoaderCircle, MapPin, Search, X } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { useGeocode } from "@/lib/api/hooks";
import type { SelectedPoint } from "@/lib/locations";

interface Props {
  bounds: number[] | undefined;
  onSelect: (point: SelectedPoint) => void;
}

function addressParts(displayName: string): {
  primary: string;
  secondary: string;
} {
  const [primary, ...rest] = displayName.split(",").map((part) => part.trim());
  return {
    primary: primary || displayName,
    secondary: rest.join(", "),
  };
}

export function LocationSearch({ bounds, onSelect }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState(false);
  const search = useGeocode(submittedQuery, bounds);
  const canSubmit = query.trim().length >= 3 && bounds !== undefined;

  useEffect(() => {
    function closeOnOutsideClick(event: PointerEvent) {
      if (
        rootRef.current &&
        event.target instanceof Node &&
        !rootRef.current.contains(event.target)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmittedQuery(query.trim());
    setOpen(true);
  }

  function clear() {
    setQuery("");
    setSubmittedQuery(null);
    setOpen(false);
  }

  return (
    <div className="relative w-[min(25rem,calc(100vw-2rem))]" ref={rootRef}>
      <form
        aria-label="Search within City of Melbourne"
        className="flex h-10 items-center rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-sm transition-[border-color,box-shadow] focus-within:border-[var(--accent-primary)] focus-within:shadow-md"
        onSubmit={submit}
        role="search"
      >
        <MapPin
          aria-hidden
          className="ml-3 h-4 w-4 shrink-0 text-[var(--accent-primary)]"
          strokeWidth={1.5}
        />
        <input
          aria-expanded={open}
          aria-haspopup="listbox"
          autoComplete="off"
          className="min-w-0 flex-1 bg-transparent px-2.5 text-sm outline-none placeholder:text-[var(--text-muted)]"
          inputMode="search"
          onBlur={() => setFocused(false)}
          onChange={(event) => {
            setQuery(event.target.value);
            if (event.target.value.trim() !== submittedQuery) setOpen(false);
          }}
          onFocus={() => {
            setFocused(true);
            if (submittedQuery && query.trim() === submittedQuery) setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
          }}
          placeholder="Search an address or place"
          type="text"
          value={query}
        />
        {focused && canSubmit && !open && (
          <span className="hidden shrink-0 text-[10px] font-medium text-[var(--text-muted)] sm:inline">
            Press Enter
          </span>
        )}
        {query && (
          <button
            aria-label="Clear search"
            className="rounded-md p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-muted)] hover:text-[var(--text-primary)]"
            onClick={clear}
            type="button"
          >
            <X className="h-4 w-4" strokeWidth={1.5} />
          </button>
        )}
        <button
          aria-label="Search"
          className="m-1.5 flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-md bg-[var(--accent-primary)] px-2 text-[var(--bg-surface)] transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canSubmit || search.isFetching}
          type="submit"
        >
          {search.isFetching ? (
            <LoaderCircle className="h-4 w-4 animate-spin" strokeWidth={1.5} />
          ) : (
            <Search className="h-4 w-4" strokeWidth={1.5} />
          )}
          <span className="hidden text-xs font-semibold sm:inline">
            {search.isFetching ? "Searching" : "Search"}
          </span>
        </button>
      </form>

      {open && submittedQuery && (
        <div className="absolute inset-x-0 top-12 overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-xl">
          <div aria-live="polite">
            {search.isFetching && (
              <p className="px-4 py-4 text-sm text-[var(--text-muted)]">
                Searching within the City of Melbourne…
              </p>
            )}

            {search.error && (
              <p className="px-4 py-4 text-sm text-[var(--state-error)]">
                {search.error.message}
              </p>
            )}

            {search.data?.length === 0 && (
              <div className="px-4 py-4">
                <p className="text-sm font-medium">No matching location found</p>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  Try a street address, landmark, or business name within the
                  municipality.
                </p>
              </div>
            )}
          </div>

          {search.data && search.data.length > 0 && (
            <ul aria-label="Address results" role="listbox">
              {search.data.map((result) => {
                const address = addressParts(result.displayName);
                return (
                  <li
                    className="border-b border-[var(--border-default)] last:border-b-0"
                    key={result.id}
                  >
                    <button
                      className="flex w-full items-start gap-3 px-3.5 py-3 text-left transition-colors hover:bg-[var(--bg-surface-muted)]"
                      onClick={() => {
                        setQuery(result.displayName);
                        setSubmittedQuery(null);
                        setOpen(false);
                        onSelect({ lat: result.lat, lon: result.lon });
                      }}
                      role="option"
                      type="button"
                    >
                      <MapPin
                        aria-hidden
                        className="mt-0.5 h-4 w-4 shrink-0 text-[var(--text-muted)]"
                        strokeWidth={1.5}
                      />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">
                          {address.primary}
                        </span>
                        {address.secondary && (
                          <span className="mt-0.5 block line-clamp-2 text-xs leading-relaxed text-[var(--text-muted)]">
                            {address.secondary}
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          <p className="border-t border-[var(--border-default)] px-3.5 py-2 text-[10px] text-[var(--text-muted)]">
            Search ©{" "}
            <a
              className="underline underline-offset-2 hover:text-[var(--text-primary)]"
              href="https://www.openstreetmap.org/copyright"
              rel="noreferrer"
              target="_blank"
            >
              OpenStreetMap contributors
            </a>
          </p>
        </div>
      )}
    </div>
  );
}
