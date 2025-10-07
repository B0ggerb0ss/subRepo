export type FieldNote = {
  id: string;
  author: string;
  avatar: string;
  timestamp: string;
  note: string;
  tags: string[];
};

export const fieldNotes: FieldNote[] = [
  {
    id: 'note-1',
    author: 'Asha Raman',
    avatar: 'AR',
    timestamp: 'Today · 08:15',
    note: 'Observed minor yellow rust cluster on north plot. Recommend targeted fungicide within 24h.',
    tags: ['wheat', 'yellow-rust']
  },
  {
    id: 'note-2',
    author: 'Diego Morales',
    avatar: 'DM',
    timestamp: 'Yesterday · 17:40',
    note: 'Updated irrigation schedule synced from Agronomy Cloud, expect humidity spike overnight.',
    tags: ['irrigation', 'sync']
  }
];

export type Integration = {
  id: string;
  name: string;
  description: string;
  status: 'Active' | 'Paused';
  cadence: string;
};

export const integrations: Integration[] = [
  {
    id: 'int-1',
    name: 'Agronomy Cloud',
    description: 'Two-way sync with central agronomy platform for annotations and device updates.',
    status: 'Active',
    cadence: '5 min'
  },
  {
    id: 'int-2',
    name: 'Operations Pager',
    description: 'Escalates critical failures to duty engineer via PagerDuty.',
    status: 'Paused',
    cadence: 'On-demand'
  }
];
