import axios from 'axios';
import { Incident, Stats, HeatmapPoint } from '../types/dashboard';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const apiClient = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const dashboardService = {
  getIncidents: async (limit = 20): Promise<Incident[]> => {
    const { data } = await apiClient.get<Incident[]>(`/incidents?limit=${limit}`);
    return data;
  },

  getStats: async (): Promise<Stats> => {
    const { data } = await apiClient.get<Stats>('/stats');
    return data;
  },

  getHeatmap: async (): Promise<HeatmapPoint[]> => {
    const { data } = await apiClient.get<HeatmapPoint[]>('/heatmap');
    return data;
  },

  acknowledgeIncident: async (id: string): Promise<string> => {
    await apiClient.post(`/incidents/${id}/ack`);
    return id;
  },

  markFalsePositive: async (id: string): Promise<string> => {
    await apiClient.post(`/incidents/${id}/false-positive`);
    return id;
  },

  getFeedUrl: () => `${API_URL}/feed`,
  
  getWsUrl: () => {
    const wsProtocol = API_URL.startsWith('https') ? 'wss' : 'ws';
    return `${wsProtocol}://${API_URL.replace(/^https?:\/\//, '')}/ws/events`;
  }
};
