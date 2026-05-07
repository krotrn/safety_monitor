import { useEffect, useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { dashboardService } from "../services/api";
import { Incident, Stats, WebSocketEvent } from "../types/dashboard";

export const useDashboardWebSocket = () => {
  const queryClient = useQueryClient();
  const [liveAlerts, setLiveAlerts] = useState<Incident[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const wsUrl = dashboardService.getWsUrl();

    const connectWs = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        const data: WebSocketEvent = JSON.parse(event.data);

        if (data.type === "ping") {
          queryClient.invalidateQueries({ queryKey: ['heatmap'] });
          return;
        }

        if (data.action_tier === "alert" || data.action_tier === "flag") {
          const alertId = data.frame_id || Date.now().toString();
          const newAlert: Incident = { 
            id: alertId,
            alertId, 
            camera_id: data.camera_id || '',
            severity_score: data.severity_score || 0,
            event_type: data.event_type || 'Unknown',
            action_tier: data.action_tier,
            acknowledged: false, 
            false_positive: false, 
            source_id: data.source_id || '',
            timestamp: data.timestamp || new Date().toISOString() 
          };

          setLiveAlerts((prev) => {
            if (prev.some(a => a.event_type === newAlert.event_type)) {
              return prev;
            }
            return [newAlert, ...prev].slice(0, 3);
          }); 

          queryClient.setQueryData<Incident[]>(['incidents'], (old) => {
            if (!old) return [newAlert];
            return [newAlert, ...old].slice(0, 20);
          });

          queryClient.setQueryData<Stats>(['stats'], (old) => {
            if (!old) return old;
            return {
              ...old,
              total_incidents: old.total_incidents + 1,
            };
          });
          queryClient.invalidateQueries({ queryKey: ['heatmap'] });

          setTimeout(() => {
            setLiveAlerts(prev => prev.filter(a => a.alertId !== alertId));
          }, 5000);
        }
      };

      ws.onclose = () => {
        setTimeout(connectWs, 2000);
      };
    };

    connectWs();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [queryClient]);

  const removeAlert = (alertId: string) => {
    setLiveAlerts(prev => prev.filter(a => a.alertId !== alertId));
  };

  return { liveAlerts, removeAlert };
};
