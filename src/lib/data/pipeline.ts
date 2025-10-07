export type PipelineStage = {
  id: string;
  name: string;
  description: string;
  status: 'idle' | 'running' | 'degraded' | 'blocked';
  metrics: {
    label: string;
    value: string;
  }[];
};

export const pipelineStages: PipelineStage[] = [
  {
    id: 'capture',
    name: 'Capture',
    description: 'Edge cameras collect multispectral leaf imagery with adaptive exposure.',
    status: 'running',
    metrics: [
      { label: 'FPS', value: '24' },
      { label: 'Resolution', value: '1920×1080' }
    ]
  },
  {
    id: 'preprocess',
    name: 'Pre-process',
    description: 'Color normalisation and ROI extraction optimised for Raspberry Pi GPU.',
    status: 'running',
    metrics: [
      { label: 'Latency', value: '8 ms' },
      { label: 'Drop Rate', value: '0.3%' }
    ]
  },
  {
    id: 'hailo-infer',
    name: 'Infer (Hailo-RT)',
    description: 'Quantised model executes on Hailo-8 accelerator with batching.',
    status: 'running',
    metrics: [
      { label: 'Latency', value: '12 ms' },
      { label: 'Utilisation', value: '78%' }
    ]
  },
  {
    id: 'postprocess',
    name: 'Post-process',
    description: 'Bounding box filtering and disease scoring on-device.',
    status: 'idle',
    metrics: [
      { label: 'Queue', value: '2 frames' },
      { label: 'Confidence', value: '0.92 avg' }
    ]
  },
  {
    id: 'sync',
    name: 'Sync',
    description: 'Results synced via MQTT to Agronomy Cloud with offline cache.',
    status: 'degraded',
    metrics: [
      { label: 'Latency', value: '250 ms' },
      { label: 'Retransmits', value: '4' }
    ]
  }
];
