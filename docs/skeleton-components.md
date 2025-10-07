# Skeleton UI 3 Component Mapping

| UI Need | Skeleton UI 3 Component(s) | Usage Notes |
| --- | --- | --- |
| App shell structure | `AppShell`, `Surface`, `Drawer`, `Button`, `Tooltip` | `AppShell` manages header/nav, `Drawer` for mobile side rail.
| KPI tiles | `Card`, `Badge`, `Icon` | Wrap metrics in `Card` with `variant="soft"`, status using `Badge` tokens.
| Edge pipeline stepper | `Stepper`, `Step`, `Divider` | Bind to an array of pipeline stages, mark completed/in-progress.
| Live monitor | `Card`, `Tabs`, `Chip`, `Switch`, `Meter` | `Switch` toggles auto-refresh, `Meter` for queue depth placeholder.
| Dataset table | `Table`, `TableRow`, `TableCell`, `Chip` | Use responsive table classes, status chips for quick glance.
| Deployment checklist | `ProgressRadial`, `Accordion`, `List` | `ProgressRadial` shows completion percentage, `Accordion` reveals remediation items.
| Notes & integrations | `Card`, `Tag`, `Avatar` | Provide context and ownership, `Tag` for categories.
| Footer actions | `ButtonGroup`, `Link` | Quick access to docs/support; use `ButtonGroup` for toggles.
| Theme toggle | `ThemeSelect`, `IconButton` | Provided by Skeleton `ThemeStore` utilities.

## References
- Skeleton UI 3 documentation (https://www.skeleton.dev) outlines the updated `AppShell` API with slot props for nav and aside content.
- Tailwind & Skeleton tokens: use classes like `bg-surface-50`, `text-secondary-500`, and spacing scale `gap-6`.
- Use `data` stores for global states: `ThemeStore` from `@skeletonlabs/skeleton`.

