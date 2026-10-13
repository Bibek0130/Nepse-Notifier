import { useEffect, useState } from "react";

// Hash routes keep the app deployable as static files: #/, #/stock/NABIL, #/quotes, #/status
function parse(hash) {
  const [page = "", param] = hash.replace(/^#\/?/, "").split("/");
  return { page: page || "overview", param: param ? decodeURIComponent(param).toUpperCase() : null };
}

export function useRoute() {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const stockHref = (symbol) => `#/stock/${encodeURIComponent(symbol)}`;
