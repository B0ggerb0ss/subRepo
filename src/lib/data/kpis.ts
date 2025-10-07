export type KpiCard = {
  id: string;
  label: string;
  value: string;
  delta?: {
    value: string;
    trend: 'up' | 'down' | 'flat';
  };
  tooltip: string;
};

export const kpiCards: KpiCard[] = [
  {
    id: 'accuracy',
    label: 'Detection Accuracy',
    value: '97.2%',
    delta: { value: '+1.1%', trend: 'up' },
    tooltip: 'Composite accuracy from last 10k labeled images.'
  },
  {
    id: 'latency',
    label: 'Median Latency',
    value: '34 ms',
    delta: { value: '-6 ms', trend: 'down' },
    tooltip: 'End-to-end inference latency including pre/post processing.'
  },
  {
    id: 'uptime',
    label: 'Uptime (7d)',
    value: '99.2%',
    delta: { value: '-0.3%', trend: 'down' },
    tooltip: 'Percentage of time pipeline executed without interruption.'
  },
  {
    id: 'throughput',
    label: 'Sample Throughput',
    value: '680 imgs/hr',
    delta: { value: '+45', trend: 'up' },
    tooltip: 'Average processed samples per hour across devices.'
  }
];
