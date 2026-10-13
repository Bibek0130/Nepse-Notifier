import { useEffect, useState } from "react";

const query = "(prefers-color-scheme: dark)";

/** "light" or "dark", following the OS setting live. Charts need it to restyle. */
export function useColorScheme() {
  const [scheme, setScheme] = useState(() => (window.matchMedia?.(query).matches ? "dark" : "light"));
  useEffect(() => {
    const mql = window.matchMedia?.(query);
    if (!mql) return undefined;
    const onChange = (e) => setScheme(e.matches ? "dark" : "light");
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return scheme;
}

/** Read a CSS custom property from :root. */
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
