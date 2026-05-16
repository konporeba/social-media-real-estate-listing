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
    let reconnectDelay = 3_000;
    const MAX_RECONNECT_DELAY = 30_000;

    function connect() {
      if (closed) return;
      es = new EventSource(url, { withCredentials: true });
      es.onmessage = (e) => {
        if (!e.data || e.data.startsWith(':')) return;
        try {
          onEventRef.current(JSON.parse(e.data) as SSEEvent);
          reconnectDelay = 3_000; // reset backoff on successful message
        } catch {
          console.warn('[useRunStream] Failed to parse SSE frame:', e.data);
        }
      };
      es.onerror = () => {
        es.close();
        if (!closed) {
          setTimeout(connect, reconnectDelay);
          reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
        }
      };
    }

    connect();
    return () => {
      closed = true;
      es?.close();
    };
  }, [runId]);
}
