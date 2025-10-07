export type Alert = {
  id: string;
  severity: 'low' | 'medium' | 'high';
  title: string;
  description: string;
  timestamp: string;
};

export const alerts: Alert[] = [
  {
    id: 'alert-1',
    severity: 'medium',
    title: 'Sync latency above SLA',
    description: 'MQTT acknowledgements delayed beyond 200 ms threshold on Field-RPI-03.',
    timestamp: '2m ago'
  },
  {
    id: 'alert-2',
    severity: 'low',
    title: 'Thermal drift trending',
    description: 'Hailo module temperature trending upwards, consider reducing batch size.',
    timestamp: '14m ago'
  }
];

export type Batch = {
  id: string;
  capturedAt: string;
  device: string;
  leafCount: number;
  diseaseHits: number;
  status: 'Ready' | 'Syncing' | 'Flagged';
};

export const recentBatches: Batch[] = [
  {
    id: 'BCH-3421',
    capturedAt: '2024-05-11 09:24',
    device: 'Field-RPI-01',
    leafCount: 128,
    diseaseHits: 12,
    status: 'Ready'
  },
  {
    id: 'BCH-3420',
    capturedAt: '2024-05-11 09:10',
    device: 'Field-RPI-03',
    leafCount: 96,
    diseaseHits: 4,
    status: 'Syncing'
  },
  {
    id: 'BCH-3419',
    capturedAt: '2024-05-11 08:55',
    device: 'Lab-RPI-02',
    leafCount: 144,
    diseaseHits: 0,
    status: 'Flagged'
  }
];

export type ChecklistItem = {
  id: string;
  label: string;
  status: 'pass' | 'warn' | 'fail';
  detail: string;
  action: string;
};

export const readinessChecklist: ChecklistItem[] = [
  {
    id: 'diag',
    label: 'Diagnostics',
    status: 'pass',
    detail: 'All hardware self-checks completed without errors.',
    action: 'Review full diagnostic log'
  },
  {
    id: 'thermal',
    label: 'Thermals',
    status: 'warn',
    detail: 'Hailo module averaging 72°C, above preferred 68°C.',
    action: 'Reduce batch size or enable fan boost'
  },
  {
    id: 'storage',
    label: 'Storage',
    status: 'pass',
    detail: '68% of edge storage available.',
    action: 'No action required'
  },
  {
    id: 'connectivity',
    label: 'Connectivity',
    status: 'fail',
    detail: 'Intermittent LTE packet loss detected.',
    action: 'Switch to Wi-Fi fallback or retry later'
  }
];
