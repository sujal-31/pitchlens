import { useEffect, useRef, useState, useCallback } from 'react';
import { tokenStorage } from '../lib/api';
import type { PipelineStage, WSEvent, PartialResult } from '../types/websocket';

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
const INITIAL_BACKOFF_MS = 1000;
const MAX_RECONNECT_ATTEMPTS = 3;

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'failed';

export interface AnalysisWebSocketState {
  currentStage: PipelineStage | null;
  partialResults: PartialResult[];
  isComplete: boolean;
  error: string | null;
  connectionStatus: ConnectionStatus;
  finalData: Record<string, unknown> | null;
}

export function useAnalysisWebSocket(analysisId: string | undefined) {
  const [state, setState] = useState<AnalysisWebSocketState>({
    currentStage: null,
    partialResults: [],
    isComplete: false,
    error: null,
    connectionStatus: 'connecting',
    finalData: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!analysisId || !mountedRef.current) return;

    const token = tokenStorage.getAccessToken();
    if (!token) {
      setState(prev => ({
        ...prev,
        error: 'Authentication required. Please sign in.',
        connectionStatus: 'failed',
      }));
      return;
    }

    cleanup();

    const url = `${WS_BASE_URL}/ws/analysis/${analysisId}?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      reconnectAttemptRef.current = 0;
      setState(prev => ({
        ...prev,
        connectionStatus: 'connected',
        error: null,
      }));
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;

      try {
        const wsEvent: WSEvent = JSON.parse(event.data);

        switch (wsEvent.event_type) {
          case 'stage_change':
            setState(prev => ({
              ...prev,
              currentStage: wsEvent.stage ?? prev.currentStage,
            }));
            break;

          case 'partial_result':
            if (wsEvent.data) {
              const result: PartialResult = {
                category: (wsEvent.data.category as string) ?? 'unknown',
                score: (wsEvent.data.score as number) ?? 0,
                reasoning: wsEvent.data.reasoning as string | undefined,
                suggestions: wsEvent.data.suggestions as string[] | undefined,
              };
              setState(prev => ({
                ...prev,
                partialResults: [...prev.partialResults, result],
              }));
            }
            break;

          case 'complete':
            setState(prev => ({
              ...prev,
              isComplete: true,
              currentStage: 'complete',
              finalData: wsEvent.data ?? null,
            }));
            cleanup();
            break;

          case 'error':
            setState(prev => ({
              ...prev,
              currentStage: 'failed',
              error: (wsEvent.data?.message as string) ?? 'Analysis failed',
            }));
            cleanup();
            break;

          case 'heartbeat':
            // Keep-alive, no state update needed
            break;
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onerror = () => {
      // onclose will handle reconnection logic
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;

      // Don't reconnect if analysis is already complete or explicitly failed
      if (state.isComplete || state.currentStage === 'failed') return;

      attemptReconnect();
    };
  }, [analysisId, cleanup, state.isComplete, state.currentStage]);

  const attemptReconnect = useCallback(() => {
    if (!mountedRef.current) return;

    if (reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
      setState(prev => ({
        ...prev,
        connectionStatus: 'failed',
        error: 'Connection lost. Unable to reconnect after 3 attempts.',
      }));
      return;
    }

    reconnectAttemptRef.current += 1;
    const backoffMs = INITIAL_BACKOFF_MS * Math.pow(2, reconnectAttemptRef.current - 1);

    setState(prev => ({
      ...prev,
      connectionStatus: 'reconnecting',
    }));

    reconnectTimerRef.current = setTimeout(() => {
      if (mountedRef.current) {
        connect();
      }
    }, backoffMs);
  }, [connect]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId]);

  return state;
}
