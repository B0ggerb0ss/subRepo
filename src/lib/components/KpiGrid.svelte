<script lang="ts">
  import { Card, Icon, Tooltip } from '@skeletonlabs/skeleton';
  import type { KpiCard } from '$data/kpis';
  export let kpis: KpiCard[] = [];

  const trendIcon = {
    up: 'mdi:trending-up',
    down: 'mdi:trending-down',
    flat: 'mdi:trending-neutral'
  } as const;
</script>

<section aria-labelledby="kpi-heading" class="space-y-4">
  <div class="flex items-center justify-between">
    <h2 id="kpi-heading" class="text-lg font-semibold tracking-tight">System Health</h2>
    <p class="text-sm text-muted-foreground">Edge fleet telemetry updated 30s ago</p>
  </div>
  <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
    {#each kpis as kpi}
      <Card variant="soft" class="group hover:-translate-y-1 transition-transform">
        <div class="flex items-start justify-between">
          <div>
            <p class="text-sm font-medium text-muted-foreground">{kpi.label}</p>
            <p class="mt-2 text-2xl font-semibold">{kpi.value}</p>
          </div>
          {#if kpi.delta}
            <Tooltip message={kpi.tooltip} placement="top">
              <span class="inline-flex items-center gap-1 rounded-full bg-surface-100 px-2 py-1 text-xs font-semibold">
                <Icon name={trendIcon[kpi.delta.trend]} class={kpi.delta.trend === 'down' ? 'text-error-500' : 'text-success-500'} />
                {kpi.delta.value}
              </span>
            </Tooltip>
          {/if}
        </div>
        <p class="mt-3 text-sm text-muted-foreground leading-relaxed">{kpi.tooltip}</p>
      </Card>
    {/each}
  </div>
</section>
