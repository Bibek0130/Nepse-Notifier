import { useEffect, useState } from "react";
import { marketApi } from "../../api/client";

export function useMarket() {
  const [state, setState] = useState({ loading: true, error: null, quotes: [], summary: null });

  useEffect(() => {
    let cancelled = false;
    Promise.all([marketApi.latestQuotes(), marketApi.summary()])
      .then(([quotes, summary]) => !cancelled && setState({ loading: false, error: null, quotes: quotes || [], summary }))
      .catch((error) => !cancelled && setState((s) => ({ ...s, loading: false, error })));
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
