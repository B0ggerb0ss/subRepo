<script lang="ts">
  import { Card, Stepper } from '@skeletonlabs/skeleton';
  import type { PipelineStage } from '$data/pipeline';
  export let stages: PipelineStage[] = [];
</script>

<section aria-labelledby="pipeline-heading" class="space-y-5">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div>
      <h2 id="pipeline-heading" class="text-lg font-semibold tracking-tight">Edge Pipeline</h2>
      <p class="text-sm text-muted-foreground">Optimised for Raspberry Pi 5 & Hailo-RT runtime</p>
    </div>
    <span class="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      Pipeline status
      <span class="inline-flex items-center gap-1 rounded-full bg-success-100 px-2 py-1 text-success-700">
        <span class="h-1.5 w-1.5 rounded-full bg-success-500 animate-ping"></span>
        Active
      </span>
    </span>
  </div>

  <Stepper orientation="horizontal" class="overflow-x-auto">
    {#each stages as stage, index}
      <Stepper.Step index={index + 1} title={stage.name} state={stage.status === 'blocked' ? 'error' : stage.status === 'degraded' ? 'warning' : 'complete'}>
        <Card padding="lg" class="space-y-3">
          <p class="text-sm text-muted-foreground">{stage.description}</p>
          <div class="flex flex-wrap gap-2">
            {#each stage.metrics as metric}
              <span class="inline-flex items-center gap-2 rounded-full bg-surface-100 px-3 py-1 text-xs font-semibold">
                <span class="font-medium text-muted-foreground">{metric.label}</span>
                <span class="text-on-surface-variant">{metric.value}</span>
              </span>
            {/each}
          </div>
        </Card>
      </Stepper.Step>
    {/each}
  </Stepper>
</section>
