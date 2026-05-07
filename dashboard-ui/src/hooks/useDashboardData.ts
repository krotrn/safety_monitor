import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { dashboardService } from "../services/api";
import { Incident, Stats } from "../types/dashboard";

export const useDashboardData = () => {
  const incidentsQuery = useQuery({
    queryKey: ['incidents'],
    queryFn: () => dashboardService.getIncidents(),
  });

  const statsQuery = useQuery({
    queryKey: ['stats'],
    queryFn: () => dashboardService.getStats(),
  });

  const heatmapQuery = useQuery({
    queryKey: ['heatmap'],
    queryFn: () => dashboardService.getHeatmap(),
  });

  return {
    incidents: incidentsQuery.data || [],
    stats: statsQuery.data,
    heatmapPoints: heatmapQuery.data || [],
    isLoading: incidentsQuery.isLoading || statsQuery.isLoading || heatmapQuery.isLoading,
  };
};

export const useDashboardActions = () => {
  const queryClient = useQueryClient();

  const ackMutation = useMutation({
    mutationFn: (id: string) => dashboardService.acknowledgeIncident(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['incidents'] });
      const previousIncidents = queryClient.getQueryData<Incident[]>(['incidents']);
      if (previousIncidents) {
        queryClient.setQueryData<Incident[]>(
          ['incidents'], 
          previousIncidents.map(inc => inc.id === id ? { ...inc, acknowledged: true } : inc)
        );
      }
      return { previousIncidents };
    },
    onError: (_err, _id, context) => {
      if (context?.previousIncidents) {
        queryClient.setQueryData(['incidents'], context.previousIncidents);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['incidents'] });
    }
  });

  const fpMutation = useMutation({
    mutationFn: (id: string) => dashboardService.markFalsePositive(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['incidents'] });
      const previousIncidents = queryClient.getQueryData<Incident[]>(['incidents']);
      if (previousIncidents) {
        queryClient.setQueryData<Incident[]>(
          ['incidents'], 
          previousIncidents.map(inc => inc.id === id ? { ...inc, false_positive: true } : inc)
        );
      }
      return { previousIncidents };
    },
    onError: (_err, _id, context) => {
      if (context?.previousIncidents) {
        queryClient.setQueryData(['incidents'], context.previousIncidents);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['incidents'] });
    }
  });

  return {
    acknowledge: ackMutation.mutate,
    markFalsePositive: fpMutation.mutate,
    isAckPending: ackMutation.isPending,
    isFpPending: fpMutation.isPending,
  };
};
