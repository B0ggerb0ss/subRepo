<script lang="ts">
  import { Card, Chip, Icon } from '@skeletonlabs/skeleton';
  import { fieldNotes, integrations } from '$data/notes';
</script>

<section aria-labelledby="field-heading" class="grid gap-4 xl:grid-cols-3">
  <Card class="xl:col-span-2 space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 id="field-heading" class="text-lg font-semibold tracking-tight">Field Notes</h2>
        <p class="text-sm text-muted-foreground">Latest agronomist context from deployed plots</p>
      </div>
      <Chip variant="soft" tone="primary">{fieldNotes.length} updates</Chip>
    </div>
    <ul class="space-y-3">
      {#each fieldNotes as note}
        <li class="rounded-xl border border-surface-200 px-4 py-3">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center gap-3">
              <span class="flex h-10 w-10 items-center justify-center rounded-full bg-primary-500/10 text-primary-600 font-semibold">
                {note.avatar}
              </span>
              <div>
                <p class="font-semibold text-on-surface">{note.author}</p>
                <p class="text-xs text-muted-foreground">{note.timestamp}</p>
              </div>
            </div>
            <div class="flex flex-wrap gap-2">
              {#each note.tags as tag}
                <Chip tone="surface" variant="outline" class="uppercase text-[11px] tracking-wide">{tag}</Chip>
              {/each}
            </div>
          </div>
          <p class="mt-3 text-sm leading-relaxed text-on-surface">{note.note}</p>
        </li>
      {/each}
    </ul>
  </Card>

  <Card class="space-y-4">
    <div class="flex items-center gap-3">
      <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-secondary-500/15 text-secondary-600">
        <Icon name="mdi:lan-connect" class="h-6 w-6" />
      </div>
      <div>
        <h3 class="text-base font-semibold">Integrations</h3>
        <p class="text-sm text-muted-foreground">Connect telemetry to downstream tools</p>
      </div>
    </div>
    <ul class="space-y-3">
      {#each integrations as integration}
        <li class="rounded-xl border border-surface-200 px-3 py-3">
          <div class="flex items-center justify-between">
            <div>
              <p class="font-semibold">{integration.name}</p>
              <p class="text-sm text-muted-foreground">{integration.description}</p>
            </div>
            <Chip tone={integration.status === 'Active' ? 'success' : 'warning'} variant="soft">{integration.status}</Chip>
          </div>
          <p class="mt-2 text-xs text-muted">Sync cadence: {integration.cadence}</p>
        </li>
      {/each}
    </ul>
    <button class="inline-flex items-center gap-2 text-sm font-semibold text-primary-500 hover:text-primary-600">
      Manage integrations
      <Icon name="mdi:arrow-right" class="h-4 w-4" />
    </button>
  </Card>
</section>
