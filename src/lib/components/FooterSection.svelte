<script lang="ts">
  import { Button, ButtonGroup, Icon, Switch } from '@skeletonlabs/skeleton';
  import { writable } from 'svelte/store';

  const telemetryOptIn = writable(true);
</script>

<footer class="mt-12 rounded-3xl bg-surface-100 px-6 py-6 text-sm text-muted-foreground">
  <div class="flex flex-wrap items-center justify-between gap-4">
    <div class="space-y-2">
      <p class="text-base font-semibold text-on-surface">Need support?</p>
      <p>Access deployment runbooks, CLI commands, and escalation workflows.</p>
      <ButtonGroup>
        <Button variant="outline">
          <Icon name="mdi:book-open-variant" class="h-4 w-4" />
          Docs
        </Button>
        <Button variant="outline">
          <Icon name="mdi:message-flash" class="h-4 w-4" />
          Contact Support
        </Button>
      </ButtonGroup>
    </div>
    <div class="rounded-2xl bg-surface-50 px-4 py-4 shadow-inner">
      <label class="flex items-center gap-3">
        <Switch bind:checked={$telemetryOptIn} />
        <div>
          <p class="font-semibold text-on-surface">Share anonymised telemetry</p>
          <p class="text-xs">Improve Hailo-RT scheduling insights by sharing usage metrics.</p>
        </div>
      </label>
    </div>
  </div>
</footer>
