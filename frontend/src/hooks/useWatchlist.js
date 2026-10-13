import { useCallback, useSyncExternalStore } from "react";

// Starred stocks live in this browser only. Email watchlists are set from the link in each digest.
const KEY = "nepse.watchlist";
const EVENT = "nepse-watchlist";
const EMPTY = [];
let cached = null;

function read() {
  if (cached) return cached;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) || "[]");
    cached = Array.isArray(parsed) ? parsed.filter((s) => typeof s === "string") : EMPTY;
  } catch {
    cached = EMPTY;
  }
  return cached;
}

function write(symbols) {
  cached = [...new Set(symbols)].sort();
  try {
    window.localStorage.setItem(KEY, JSON.stringify(cached));
  } catch {
    // Storage blocked (private mode): keep the list for this page view only.
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(onChange) {
  const onStorage = (e) => {
    if (e.key === KEY) {
      cached = null;
      onChange();
    }
  };
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function useWatchlist() {
  const symbols = useSyncExternalStore(subscribe, read);
  const has = useCallback((symbol) => symbols.includes(symbol), [symbols]);
  const toggle = useCallback(
    (symbol) => write(symbols.includes(symbol) ? symbols.filter((s) => s !== symbol) : [...symbols, symbol]),
    [symbols],
  );
  return { symbols, has, toggle };
}
