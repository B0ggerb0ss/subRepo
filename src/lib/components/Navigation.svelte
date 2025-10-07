<script lang="ts">
  import { Badge, Button, Icon, Tooltip, drawerStore } from '@skeletonlabs/skeleton';
  import type { KpiCard } from '$data/kpis';
  export let environment: 'Lab' | 'Field';
  export let kpis: KpiCard[] = [];

  const openMobileNav = () => drawerStore.open('mobile-nav');
</script>

<header class="flex flex-wrap items-center justify-between gap-4 px-6 py-4 bg-surface-50/70 backdrop-blur border-b border-surface-200">
  <div class="flex items-center gap-3">
    <button
      class="inline-flex lg:hidden items-center justify-center rounded-xl border border-surface-200 p-2 text-muted-foreground"
      on:click={openMobileNav}
      aria-label="Open navigation"
    >
      <Icon name="mdi:menu" class="h-5 w-5" />
    </button>
    <div class="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-500 text-primary-50 font-semibold shadow-soft">
      LG
    </div>
    <div>
      <p class="text-lg font-semibold tracking-tight">LeafGuard Edge</p>
      <p class="text-sm text-muted-foreground">Raspberry Pi + Hailo-RT deployment</p>
    </div>
  </div>

  <div class="flex items-center gap-3 text-sm text-muted-foreground">
    <span class="hidden md:inline-flex items-center gap-2 rounded-full bg-surface-100 px-3 py-1">
      <Icon name="material-symbols:location-searching" class="h-4 w-4 text-primary-500" />
      Environment
      <Badge variant="soft" class="ml-1">{environment}</Badge>
    </span>
    <Tooltip message="Last sync 4 minutes ago">
      <Badge variant="outline" class="gap-1">
        <span class="h-2 w-2 rounded-full bg-success-500 animate-pulse" aria-hidden="true"></span>
        Healthy
      </Badge>
    </Tooltip>
  </div>

  <div class="flex items-center gap-2">
    <Button variant="ghost" class="hidden md:inline-flex">
      <Icon name="mdi:play-circle" class="h-4 w-4" />
      Start Capture
    </Button>
    <Button>
      <Icon name="mdi:rocket-launch" class="h-4 w-4" />
      Deploy Update
    </Button>
  </div>
</header>
