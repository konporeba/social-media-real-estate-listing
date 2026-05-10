import { useEffect, useRef } from 'react';
import type { SSEEvent } from '../types';

export function useRunStream(
  onEvent: (e: SSEEvent) => void,
  runId?: string,
) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const url = runId ? `/events?run_id=${runId}` : '/events';
    let es: EventSource;
    let closed = false;

    function connect() {
      if (closed) return;
      es = new EventSource(url, { withCredentials: true });
      es.onmessage = (e) => {
        if (!e.data || e.data.startsWith(':')) return;
        try {
          onEventRef.current(JSON.parse(e.data) as SSEEvent);
        } catch {
          // ignore malformed frames
        }
      };
      es.onerror = () => {
        es.close();
        if (!closed) setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      closed = true;
      es?.close();
    };
  }, [runId]);
}
