# LeafGuard Edge Dashboard

A SvelteKit + Skeleton UI 3 dashboard tailored for leaf disease detection pipelines running on Raspberry Pi devices accelerated with Hailo-RT.

## Architecture
- **Framework**: SvelteKit (Svelte 5) with TypeScript and Bun runtime scripts.
- **UI Kit**: Skeleton UI 3 components with Tailwind CSS and a custom `leaf-guard` theme.
- **Structure**: Modular, reusable sections for hero snapshot, pipeline overview, live monitor, insights, readiness, and field operations.

## Getting Started
1. Install dependencies (Bun recommended):
   ```bash
   bun install
   ```
2. Start the development server:
   ```bash
   bun run dev
   ```
3. Build for production:
   ```bash
   bun run build
   ```
4. Preview the production build:
   ```bash
   bun run preview
   ```

## Design Documents
- [UI Plan](docs/ui-design.md)
- [Skeleton UI 3 Component Mapping](docs/skeleton-components.md)

## Accessibility & Responsiveness
- Skip-to-content link and semantic headings for screen reader support.
- App Shell layout adapts to mobile with Drawer navigation.
- Theme toggle persists user preference via local storage.

## Next Steps
- Wire real telemetry sources for charts and metrics.
- Integrate authentication for deployment actions.
- Add Playwright smoke tests for core user journeys.
