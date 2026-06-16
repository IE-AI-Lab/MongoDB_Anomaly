"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface PollingState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  refresh: () => void;
}

/**
 * Generic interval-polling fetch hook. Cleanup-safe: ignores in-flight results
 * after unmount and clears its timer. `intervalMs <= 0` fetches once only.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = []
): PollingState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const aliveRef = useRef(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      if (aliveRef.current) {
        setData(result);
        setError(undefined);
      }
    } catch (e) {
      if (aliveRef.current) setError(e as Error);
    } finally {
      if (aliveRef.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    run();
    if (intervalMs > 0) {
      const id = setInterval(run, intervalMs);
      return () => {
        aliveRef.current = false;
        clearInterval(id);
      };
    }
    return () => {
      aliveRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, run, ...deps]);

  return { data, error, loading, refresh: run };
}
