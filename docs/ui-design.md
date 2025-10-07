# LeafGuard Edge Dashboard UI Plan

## Design Objectives
- Present an end-to-end view of the leaf disease detection workflow optimised for Raspberry Pi + Hailo-RT deployments.
- Surface actionable telemetry and model insights with minimal cognitive load.
- Use responsive, accessibility-first layouts leveraging Skeleton UI 3 primitives and the Tailwind design tokens they expose.

## Global Layout
- **App Shell**
  - Top navigation with brand, environment switcher (lab vs field), status badge, and deploy button.
  - Side rail collapsible on mobile housing quick links to core sections.
  - Main content uses scrollable sections, each with contextual cards.

## Page Sections
1. **Hero / System Snapshot**
   - Status summary, last sync time, CTA buttons for `Deploy Update` and `Start Capture`.
   - KPI tiles: Detection accuracy, latency, uptime, sample throughput.
2. **Edge Pipeline Overview**
   - Stepper showing stages: Capture → Pre-process → Infer (Hailo) → Post-process → Sync.
   - Inline cards for each stage with quick stats and configuration badges.
3. **Live Inference Monitor**
   - Stream preview placeholder, inference queue graph, alerts list.
   - Toggle for auto-refresh and quality options.
4. **Dataset & Model Insights**
   - Tabs for Dataset, Model, and Calibration metrics.
   - Table of recent sample batches with status chips.
   - Gradient card for model version details and changelog timeline.
5. **Deployment Readiness Checklist**
   - Checklist (progress ring) covering diagnostics, thermal status, storage, connectivity.
   - Accordion for remediation steps per failed check.
6. **Field Notes & Integrations**
   - Card grid for agronomist notes, integration webhooks, and scheduled tasks.
7. **Footer / CTA**
   - Contact support, documentation links, telemetry opt-in toggles.

## Responsiveness & Interactions
- Mobile-first: navigation collapses to sheet, KPI tiles become carousel using Skeleton `Carousel`.
- Dark/light theme toggle built into Skeleton Theme Switcher.
- All charts represented as placeholder cards to be wired later.

## Accessibility Considerations
- Minimum 4.5:1 contrast, semantic headings, skip-to-content link.
- Keyboard navigable controls, focus ring visible via Skeleton focus tokens.

