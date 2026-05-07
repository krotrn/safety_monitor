export type ActionTier = "silent" | "flag" | "alert";

export interface Incident {
  id: string;
  timestamp: string;
  camera_id: string;
  severity_score: number;
  event_type: string;
  action_tier: ActionTier;
  acknowledged: boolean;
  false_positive: boolean;
  source_id: string;
  alertId?: string;
}

export interface Stats {
  total_incidents: number;
  active_incidents: number;
  completed_incidents: number;
  average_severity: number;
  recent_incidents: Incident[];
}

export interface HeatmapPoint {
  x: number;
  y: number;
}

export interface WebSocketEvent extends Partial<Incident> {
  type?: string;
  frame_id?: string;
}
