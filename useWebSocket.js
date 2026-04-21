import { useState, useEffect, useRef } from 'react';

export function useWebSocket(url) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState(null);
  const [error, setError] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const retryCountRef = useRef(0);
  const MAX_RETRIES = 5;

  useEffect(() => {
    // Clean up any existing connection and timeout
    if (wsRef.current) {
      wsRef.current.close();
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }

    const connect = () => {
      try {
        console.log(`Attempting WebSocket connection to: ${url} (attempt ${retryCountRef.current + 1})`);
        const ws = new WebSocket(url);

        ws.onopen = () => {
          console.log('✓ WebSocket connected successfully');
          setIsConnected(true);
          setError(null);
          retryCountRef.current = 0;
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            console.log('WebSocket message received:', data);
            setLastMessage(data);
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };

        ws.onerror = (event) => {
          console.error('WebSocket error:', event);
          setError('WebSocket connection error');
          setIsConnected(false);
        };

        ws.onclose = (event) => {
          console.log(`WebSocket disconnected (code: ${event.code})`);
          setIsConnected(false);

          // Reconnect with exponential backoff
          if (retryCountRef.current < MAX_RETRIES) {
            retryCountRef.current++;
            const delay = Math.min(1000 * Math.pow(2, retryCountRef.current), 10000);
            console.log(`Reconnecting in ${delay}ms...`);
            reconnectTimeoutRef.current = setTimeout(connect, delay);
          } else {
            console.error('Max WebSocket retries reached. Giving up.');
            setError('Failed to connect to WebSocket server');
          }
        };

        wsRef.current = ws;
      } catch (error) {
        console.error('Failed to create WebSocket:', error);
        setError(error.message);
      }
    };

    // Delay initial connection to avoid race conditions
    const initialDelay = setTimeout(connect, 500);

    return () => {
      clearTimeout(initialDelay);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };
  }, [url]);

  const sendMessage = (message) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  };

  return { isConnected, lastMessage, sendMessage, error };
}
