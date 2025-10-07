<script lang="ts">
  import { Card, Chip, Icon, Tabs } from '@skeletonlabs/skeleton';
  import { recentBatches } from '$data/monitoring';
</script>

<section aria-labelledby="insights-heading" class="space-y-5">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div>
      <h2 id="insights-heading" class="text-lg font-semibold tracking-tight">Dataset & Model Insights</h2>
      <p class="text-sm text-muted-foreground">Keep calibration current across field deployments</p>
    </div>
    <Chip tone="primary" variant="outline" class="uppercase tracking-wide text-xs">Model v2.4.1 · Quantised INT8</Chip>
  </div>

  <Tabs active="dataset" listClass="flex flex-wrap gap-2 border-b border-surface-200 pb-2">
    <Tabs.Item value="dataset" label="Dataset" />
    <Tabs.Item value="model" label="Model" />
    <Tabs.Item value="calibration" label="Calibration" />
  </Tabs>

  <div class="grid gap-4 lg:grid-cols-3">
    <Card class="lg:col-span-2 overflow-hidden">
      <table class="min-w-full text-left text-sm">
        <thead class="bg-surface-100 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th class="px-4 py-3">Batch</th>
            <th class="px-4 py-3">Captured</th>
            <th class="px-4 py-3">Device</th>
            <th class="px-4 py-3">Leaves</th>
            <th class="px-4 py-3">Disease hits</th>
            <th class="px-4 py-3">Status</th>
          </tr>
        </thead>
        <tbody>
          {#each recentBatches as batch, index}
            <tr class={index % 2 === 0 ? 'bg-surface-50/40' : ''}>
              <td class="px-4 py-3 font-semibold">{batch.id}</td>
              <td class="px-4 py-3">{batch.capturedAt}</td>
              <td class="px-4 py-3">{batch.device}</td>
              <td class="px-4 py-3">{batch.leafCount}</td>
              <td class="px-4 py-3">{batch.diseaseHits}</td>
              <td class="px-4 py-3">
                <Chip variant="soft" tone={batch.status === 'Flagged' ? 'error' : batch.status === 'Syncing' ? 'warning' : 'success'}>{batch.status}</Chip>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </Card>

    <Card class="space-y-4">
      <div class="flex items-center gap-3">
        <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-500/20 text-primary-600">
          <Icon name="mdi:chip" class="h-6 w-6" />
        </div>
        <div>
          <h3 class="text-base font-semibold">Model Changelog</h3>
          <p class="text-sm text-muted-foreground">Fine-tuned on 8.2k additional diseased leaves</p>
        </div>
      </div>
      <ol class="space-y-3 text-sm text-muted-foreground">
        <li>
          <span class="font-semibold text-on-surface">05 May</span> · Added rust and blight augmentation set
        </li>
        <li>
          <span class="font-semibold text-on-surface">30 Apr</span> · Improved quantisation aware training for Hailo-8
        </li>
        <li>
          <span class="font-semibold text-on-surface">22 Apr</span> · New agronomist verified annotations
        </li>
      </ol>
      <button class="inline-flex items-center gap-2 text-sm font-semibold text-primary-500 hover:text-primary-600">
        View full release notes
        <Icon name="mdi:arrow-top-right" class="h-4 w-4" />
      </button>
    </Card>
  </div>
</section>
