import { useEffect, useState } from "react";

const query = "(prefers-color-scheme: dark)";
const KEY = "nepse.theme";
const PREFS = ["auto", "light", "dark"];

function readPref() {
  try {
    const v = localStorage.getItem(KEY);
    return PREFS.includes(v) ? v : "auto";
  } catch {
    return "auto";
  }
}

/** "auto" removes data-theme so CSS follows the OS; "light"/"dark" pin it. */
function applyPref(pref) {
  const root = document.documentElement;
  if (pref === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
}

function resolve() {
  const pinned = document.documentElement.getAttribute("data-theme");
  if (pinned === "light" || pinned === "dark") return pinned;
  return window.matchMedia?.(query).matches ? "dark" : "light";
}

/** The theme switch: "auto" (follow the OS), "light" or "dark", remembered in this browser. */
export function useThemePreference() {
  const [pref, setPref] = useState(readPref);
  useEffect(() => {
    applyPref(pref);
    try {
      localStorage.setItem(KEY, pref);
    } catch {
      // Private mode or blocked storage: the choice just lasts for this visit.
    }
  }, [pref]);
  const cycle = () => setPref((p) => PREFS[(PREFS.indexOf(p) + 1) % PREFS.length]);
  return [pref, cycle];
}

/** "light" or "dark" as shown right now (OS setting or the theme switch). Charts need it to restyle. */
export function useColorScheme() {
  const [scheme, setScheme] = useState(resolve);
  useEffect(() => {
    const update = () => setScheme(resolve());
    const mql = window.matchMedia?.(query);
    mql?.addEventListener("change", update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mql?.removeEventListener("change", update);
      observer.disconnect();
    };
  }, []);
  return scheme;
}

/** Read a CSS custom property from :root. */
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
