<script lang="ts">
  import '../app.postcss';
  import { ThemeSelect, SkeletonProvider, setAppShellStore } from '@skeletonlabs/skeleton';
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';

  let theme = 'leaf-guard';

  onMount(() => {
    if (!browser) return;
    const stored = localStorage.getItem('leafguard-theme');
    if (stored) {
      theme = stored;
    }
    document.documentElement.dataset.theme = theme;
  });

  $: if (browser) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('leafguard-theme', theme);
  }

  setAppShellStore({ layout: 'sidebar' });
</script>

<SkeletonProvider>
  <slot />
  <div class="fixed bottom-4 right-4 z-50 hidden sm:flex items-center gap-2 px-3 py-2 rounded-2xl bg-surface-50/90 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-surface-50/60">
    <span class="text-sm font-medium text-muted">Theme</span>
    <ThemeSelect name="theme" class="w-32" bind:value={theme} />
  </div>
</SkeletonProvider>
