<script lang="ts">
  import { Card, Chip, Icon, Switch, Tabs } from '@skeletonlabs/skeleton';
  import { alerts } from '$data/monitoring';
  import { writable } from 'svelte/store';

  const qualityOptions = ['Balanced', 'High Fidelity', 'Bandwidth Saver'] as const;
  const activeQuality = writable<typeof qualityOptions[number]>('Balanced');
  const autoRefresh = writable(true);

  const severityColor = {
    low: 'bg-success-100 text-success-700',
    medium: 'bg-warning-100 text-warning-700',
    high: 'bg-error-100 text-error-700'
  } as const;
</script>

<section aria-labelledby="monitor-heading" class="space-y-4">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div>
      <h2 id="monitor-heading" class="text-lg font-semibold tracking-tight">Live Inference Monitor</h2>
      <p class="text-sm text-muted-foreground">Observability for streaming inference workloads</p>
    </div>
    <div class="flex items-center gap-4 text-sm text-muted-foreground">
      <label class="flex items-center gap-2">
        <span>Auto refresh</span>
        <Switch bind:checked={$autoRefresh} aria-label="Toggle auto refresh" />
      </label>
      <label class="flex items-center gap-2">
        <span>Quality</span>
        <select
          class="rounded-lg border border-surface-200 bg-transparent px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary-400"
          bind:value={$activeQuality}
        >
          {#each qualityOptions as option}
            <option class="bg-surface-50 text-on-surface" value={option}>{option}</option>
          {/each}
        </select>
      </label>
    </div>
  </div>

  <div class="grid gap-4 lg:grid-cols-3">
    <Card class="lg:col-span-2 space-y-4">
      <Tabs active="frame" listClass="grid grid-cols-3">
        <Tabs.Item value="frame" label="Inference Stream" />
        <Tabs.Item value="queue" label="Queue Depth" />
        <Tabs.Item value="thermal" label="Thermal Profile" />
      </Tabs>
      <div class="aspect-video w-full rounded-2xl border border-dashed border-surface-300 bg-gradient-to-br from-surface-100 to-surface-200 flex items-center justify-center text-muted-foreground">
        <div class="text-center space-y-2">
          <Icon name="mdi:video-outline" class="mx-auto h-10 w-10" />
          <p class="font-medium">Stream placeholder</p>
          <p class="text-sm">Connect device to preview live detections.</p>
        </div>
      </div>
    </Card>

    <Card class="space-y-4">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Active alerts</h3>
        <Chip tone="warning" variant="soft">{alerts.length}</Chip>
      </div>
      <ul class="space-y-3">
        {#each alerts as alert}
          <li class="rounded-xl border border-surface-200 px-3 py-3">
            <div class="flex items-center justify-between">
              <p class="text-sm font-semibold">{alert.title}</p>
              <span class={`inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold ${severityColor[alert.severity]}`}>
                {alert.severity}
              </span>
            </div>
            <p class="mt-2 text-sm text-muted-foreground">{alert.description}</p>
            <p class="mt-3 text-xs text-muted">{alert.timestamp}</p>
          </li>
        {/each}
      </ul>
    </Card>
  </div>
</section>
