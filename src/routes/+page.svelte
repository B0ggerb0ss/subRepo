<script lang="ts">
  import { AppShell, Drawer, Icon } from '@skeletonlabs/skeleton';
  import Navigation from '$components/Navigation.svelte';
  import HeroSection from '$components/HeroSection.svelte';
  import KpiGrid from '$components/KpiGrid.svelte';
  import PipelineStepper from '$components/PipelineStepper.svelte';
  import LiveMonitor from '$components/LiveMonitor.svelte';
  import DatasetInsights from '$components/DatasetInsights.svelte';
  import DeploymentChecklist from '$components/DeploymentChecklist.svelte';
  import FieldNotesIntegrations from '$components/FieldNotesIntegrations.svelte';
  import FooterSection from '$components/FooterSection.svelte';
  import { kpiCards } from '$data/kpis';
  import { pipelineStages } from '$data/pipeline';

  const navLinks = [
    { href: '#overview', label: 'Overview', icon: 'mdi:compass-outline' },
    { href: '#pipeline', label: 'Pipeline', icon: 'mdi:graph' },
    { href: '#monitor', label: 'Monitor', icon: 'mdi:pulse' },
    { href: '#insights', label: 'Insights', icon: 'mdi:table-eye' },
    { href: '#readiness', label: 'Readiness', icon: 'mdi:clipboard-check' },
    { href: '#field', label: 'Field Ops', icon: 'mdi:leaf-circle' }
  ];
</script>

<svelte:head>
  <title>LeafGuard Edge Dashboard</title>
  <meta name="description" content="Edge deployment control plane for Raspberry Pi & Hailo-RT leaf disease detection." />
</svelte:head>

<AppShell
  class="min-h-screen"
  regionMain="max-w-6xl mx-auto w-full px-4 sm:px-6 md:px-8 py-10"
  regionSidebar="hidden lg:flex flex-col gap-3 px-4 py-6 border-r border-surface-200"
  regionFooter="px-4 py-6"
>
  <AppShell.Header>
    <Navigation environment="Field" {kpiCards} />
  </AppShell.Header>

  <AppShell.Aside>
    <nav aria-label="Secondary">
      <ul class="space-y-1">
        {#each navLinks as link}
          <li>
            <a
              class="flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-surface-100 hover:text-on-surface"
              href={link.href}
            >
              <Icon name={link.icon} class="h-4 w-4" />
              {link.label}
            </a>
          </li>
        {/each}
      </ul>
    </nav>
  </AppShell.Aside>

  <AppShell.Main>
    <div id="main" class="space-y-12">
      <section id="overview" class="space-y-10">
        <HeroSection />
        <KpiGrid kpis={kpiCards} />
      </section>

      <section id="pipeline">
        <PipelineStepper stages={pipelineStages} />
      </section>

      <section id="monitor">
        <LiveMonitor />
      </section>

      <section id="insights">
        <DatasetInsights />
      </section>

      <section id="readiness">
        <DeploymentChecklist />
      </section>

      <section id="field">
        <FieldNotesIntegrations />
      </section>

      <FooterSection />
    </div>
  </AppShell.Main>

  <AppShell.Footer>
    <p class="text-center text-xs text-muted-foreground">© {new Date().getFullYear()} LeafGuard Analytics · Designed for edge agronomy teams.</p>
  </AppShell.Footer>
</AppShell>

<Drawer id="mobile-nav" position="left" size="xs">
  <nav aria-label="Mobile">
    <ul class="space-y-1">
      {#each navLinks as link}
        <li>
          <a class="flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-on-surface" href={link.href}>
            <Icon name={link.icon} class="h-4 w-4" />
            {link.label}
          </a>
        </li>
      {/each}
    </ul>
  </nav>
</Drawer>
