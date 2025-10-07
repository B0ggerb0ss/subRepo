<script lang="ts">
  import { Accordion, Card, Icon, Meter, ProgressRadial } from '@skeletonlabs/skeleton';
  import { readinessChecklist } from '$data/monitoring';

  const completion = Math.round(
    (readinessChecklist.filter((item) => item.status === 'pass').length / readinessChecklist.length) * 100
  );

  const statusTone: Record<typeof readinessChecklist[number]['status'], 'success' | 'warning' | 'error'> = {
    pass: 'success',
    warn: 'warning',
    fail: 'error'
  };
</script>

<section aria-labelledby="readiness-heading" class="space-y-5">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div>
      <h2 id="readiness-heading" class="text-lg font-semibold tracking-tight">Deployment Readiness</h2>
      <p class="text-sm text-muted-foreground">Validate devices before releasing new inference bundles</p>
    </div>
    <ProgressRadial value={completion} max={100} size="lg" stroke="thick">
      <span class="text-lg font-semibold">{completion}%</span>
    </ProgressRadial>
  </div>

  <Card class="space-y-4">
    <Accordion>
      {#each readinessChecklist as item}
        <Accordion.Item value={item.id} open={item.status !== 'pass'}>
          <Accordion.Trigger class="flex w-full items-center justify-between gap-4 py-3">
            <div class="flex items-center gap-3">
              <span class={`flex h-10 w-10 items-center justify-center rounded-xl bg-${statusTone[item.status]}-100 text-${statusTone[item.status]}-600`}>
                <Icon name={item.status === 'pass' ? 'mdi:check' : item.status === 'warn' ? 'mdi:alert' : 'mdi:alert-circle'} class="h-5 w-5" />
              </span>
              <div>
                <p class="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{item.label}</p>
                <p class="text-sm text-on-surface">{item.detail}</p>
              </div>
            </div>
            <Icon name="mdi:chevron-down" class="h-5 w-5 text-muted" />
          </Accordion.Trigger>
          <Accordion.Content class="pl-14 pb-4">
            <p class="text-sm text-muted-foreground">{item.action}</p>
            <Meter max={100} value={item.status === 'fail' ? 45 : item.status === 'warn' ? 70 : 100} class="mt-3" tone={statusTone[item.status]} />
          </Accordion.Content>
        </Accordion.Item>
      {/each}
    </Accordion>
  </Card>
</section>
