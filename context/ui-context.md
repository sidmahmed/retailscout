# UI Context

## Theme

Light, data-forward "civic intelligence" workspace, not a dark
technical console. The map is the primary surface, so chrome stays
neutral and quiet: white/near-white panels, thin borders instead of
heavy shadows, and color reserved for score, confidence, and category
meaning rather than decoration. Avoid false precision in the visual
language — never make a sparse/interpolated result look as crisp as an
observed one (see `code-standards.md` and architecture doc §18.4).

## Colors

Define color tokens as CSS custom properties. All components must use
these tokens — no hardcoded hex values. Suitability-score and
confidence-band colors are product concepts (architecture doc §10.4,
§18.4) and must stay consistent everywhere they appear (map hexes,
score bars, badges).

| Role                    | CSS Variable            | Value     |
| ------------------------ | ------------------------ | --------- |
| Page background           | `--bg-base`               | `#F7F8FA` |
| Surface (panels/drawers)   | `--bg-surface`            | `#FFFFFF` |
| Surface muted (map chrome)  | `--bg-surface-muted`       | `#EEF1F4` |
| Primary text                | `--text-primary`          | `#14181F` |
| Muted text                  | `--text-muted`            | `#5B6472` |
| Primary accent (brand/CTA)   | `--accent-primary`         | `#1D6F5C` |
| Border                        | `--border-default`         | `#DCE1E6` |
| Score — low (0–33)              | `--score-low`               | `#C4462B` |
| Score — moderate (34–66)         | `--score-mid`               | `#D3A324` |
| Score — strong (67–100)           | `--score-high`              | `#1D6F5C` |
| Confidence — high                  | `--confidence-high`          | `#1D6F5C` |
| Confidence — medium                 | `--confidence-medium`        | `#D3A324` |
| Confidence — low                     | `--confidence-low`           | `#B36A17` |
| Confidence — insufficient              | `--confidence-insufficient`   | `#8A93A1` |
| Error                                   | `--state-error`               | `#C4462B` |
| Success                                  | `--state-success`             | `#1D6F5C` |

Score and confidence colors are deliberately distinct palettes (warm
amber/brown for confidence vs. red/amber/green for score) so a
low-confidence *high* score is never visually confused with a
low-confidence *low* score.

## Typography

| Role      | Font                          | Variable      |
| --------- | ----------------------------- | ------------- |
| UI text   | Inter (system-ui fallback)     | `--font-sans` |
| Numerals/scores | Inter, tabular-nums enabled | `--font-sans` |
| Code/mono | JetBrains Mono                 | `--font-mono` |

Use `font-variant-numeric: tabular-nums` for all score values and
comparison tables so numbers align in columns.

## Border Radius

| Context             | Class          |
| -------------------- | -------------- |
| Inline / small UI      | `rounded-md`   |
| Cards / panels           | `rounded-lg`   |
| Modals / overlays          | `rounded-xl`   |
| Map popovers / tooltips      | `rounded-md`   |

## Component Library

shadcn/ui on top of Tailwind CSS. Components live in
`frontend/components/ui/`. Use the shadcn CLI to add new primitives
rather than writing them from scratch; keep RetailScout-specific
composites (score bars, confidence badges, evidence cards, daypart
charts) in `frontend/components/scoring/`, `frontend/components/charts/`,
and `frontend/components/locations/` per the repo structure in
`architecture.md`.

## Layout Patterns

- **Explore/Map (desktop)**: full-height MapLibre map; search and
  profile controls docked at top; results drawer slides in from the
  side on location selection; comparison tray docked at the bottom
  when 2+ locations are staged (architecture doc §18.1).
- **Explore/Map (mobile)**: map with compact top controls; selected
  location evidence opens as a bottom sheet; comparison is a separate
  full screen rather than an overlay.
- **Location result panel**: fixed evidence order — suitability +
  confidence, one-sentence interpretation, component score bars,
  positive drivers and risks, daypart foot-traffic chart, nearby
  business breakdown, worker/development evidence, source freshness
  and limitations (architecture doc §18.3). Do not reorder this
  hierarchy between screens.
- **Map layers**: suitability hexes and confidence overlay are always
  available; raw points (sensors, individual businesses, developments)
  render only after zooming in, to avoid clutter (architecture doc
  §18.2).
- **Modals/overlays**: centered, backdrop blur, `rounded-xl`.
- **Comparison tray/screen**: side-by-side component-score columns
  with raw metrics visible next to percentiles — never show a bare
  ranked list without the underlying numbers.

## Icons

Lucide React. Stroke-based icons only, 1.5px stroke. Sizes: `h-4 w-4`
for inline/badge icons, `h-5 w-5` for buttons and drawer headers.
Reserve filled icons for confidence-band indicators only, so they read
distinctly from outline navigation/action icons.
