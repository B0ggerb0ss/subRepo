<script lang="ts">
  import { Button, Card, Icon } from '@skeletonlabs/skeleton';
</script>

<section class="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
  <Card class="space-y-6 bg-gradient-to-br from-primary-500/20 via-primary-500/10 to-surface-50">
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight text-on-surface">Leaf disease intelligence at the edge</h1>
        <p class="mt-2 max-w-2xl text-sm text-primary-900/80 dark:text-primary-100">
          Monitor capture, inference, and sync in one place. Built for Raspberry Pi 5 nodes accelerated by Hailo-RT.
        </p>
      </div>
      <div class="rounded-2xl bg-surface-50/80 px-4 py-3 text-sm text-muted-foreground">
        Last sync
        <span class="ml-2 font-semibold text-on-surface">09:31</span>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-3">
      <Button size="lg">
        <Icon name="mdi:lightning-bolt" class="h-4 w-4" />
        Quick deploy
      </Button>
      <Button size="lg" variant="outline">
        <Icon name="mdi:console" class="h-4 w-4" />
        View device logs
      </Button>
    </div>
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div class="rounded-2xl border border-white/40 bg-white/40 p-4 dark:border-surface-300/40 dark:bg-surface-100/40">
        <p class="text-xs uppercase tracking-wide text-muted-foreground">Fleet</p>
        <p class="mt-1 text-2xl font-semibold text-on-surface">12</p>
        <p class="text-xs text-muted">Active devices</p>
      </div>
      <div class="rounded-2xl border border-white/40 bg-white/40 p-4 dark:border-surface-300/40 dark:bg-surface-100/40">
        <p class="text-xs uppercase tracking-wide text-muted-foreground">Edge Models</p>
        <p class="mt-1 text-2xl font-semibold text-on-surface">3</p>
        <p class="text-xs text-muted">RPI + Hailo variants</p>
      </div>
      <div class="rounded-2xl border border-white/40 bg-white/40 p-4 dark:border-surface-300/40 dark:bg-surface-100/40">
        <p class="text-xs uppercase tracking-wide text-muted-foreground">Alerts</p>
        <p class="mt-1 text-2xl font-semibold text-on-surface">2</p>
        <p class="text-xs text-muted">Open items</p>
      </div>
      <div class="rounded-2xl border border-white/40 bg-white/40 p-4 dark:border-surface-300/40 dark:bg-surface-100/40">
        <p class="text-xs uppercase tracking-wide text-muted-foreground">Firmware</p>
        <p class="mt-1 text-2xl font-semibold text-on-surface">v1.8.2</p>
        <p class="text-xs text-muted">Current version</p>
      </div>
    </div>
  </Card>
  <Card class="flex flex-col justify-between space-y-6">
    <div class="space-y-4">
      <h2 class="text-lg font-semibold tracking-tight">Edge deployment targets</h2>
      <ul class="space-y-3 text-sm">
        <li class="flex items-center gap-3">
          <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-100">
            <Icon name="mdi:raspberry-pi" class="h-5 w-5 text-primary-600" />
          </span>
          <div>
            <p class="font-semibold">Raspberry Pi 5</p>
            <p class="text-muted-foreground">64-bit OS, GPU accel enabled</p>
          </div>
        </li>
        <li class="flex items-center gap-3">
          <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-100">
            <Icon name="mdi:memory" class="h-5 w-5 text-primary-600" />
          </span>
          <div>
            <p class="font-semibold">Hailo-8 RT</p>
            <p class="text-muted-foreground">INT8 quantised runtime</p>
          </div>
        </li>
        <li class="flex items-center gap-3">
          <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-100">
            <Icon name="mdi:weather-windy" class="h-5 w-5 text-primary-600" />
          </span>
          <div>
            <p class="font-semibold">Field-ready enclosure</p>
            <p class="text-muted-foreground">IP65, solar + LTE failover</p>
          </div>
        </li>
      </ul>
    </div>
    <div class="rounded-2xl border border-dashed border-primary-300 px-4 py-4 text-sm">
      <p class="font-semibold text-on-surface">Next maintenance window</p>
      <p class="text-muted-foreground">11 May · 22:00 - 00:00 UTC</p>
    </div>
  </Card>
</section>
