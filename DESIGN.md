---
name: Jibek Joly
description: Kazakhstan synthetic dispatch workspace in Russian and Kazakh.
colors:
  bg: "#f5f3ee"
  surface: "#fff"
  surface2: "#faf8f4"
  border: "#e3ded3"
  text: "#1a2230"
  secondary: "#566070"
  muted: "#8a93a1"
  primary: "#1d5fa8"
  sand: "#e8dcc2"
  ok: "#176c47"
  warning: "#965900"
  critical: "#c0392b"
  ok-bg: "#e9f5ee"
  warn-bg: "#fff1d9"
  critical-bg: "#fceae6"
  passenger: "#6b4fbb"
  freight: "#7a5c3e"
  dark-bg: "#141c26"
  dark-surface: "#1d2835"
  dark-surface2: "#243140"
  dark-border: "#394859"
  dark-text: "#edf1f7"
  dark-secondary: "#bcc7d5"
  dark-muted: "#98a5b6"
  dark-primary: "#88baff"
  dark-sand: "#605846"
  dark-ok: "#81d9a6"
  dark-warning: "#ffc979"
  dark-critical: "#ffaaa1"
  dark-ok-bg: "#213d32"
  dark-warn-bg: "#423823"
  dark-critical-bg: "#482d31"
  dark-passenger: "#bea8ff"
  dark-freight: "#dab08a"
typography:
  display:
    fontFamily: "Inter, sans-serif"
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Inter, sans-serif"
    fontSize: "20px"
    fontWeight: 700
  title:
    fontFamily: "Inter, sans-serif"
    fontSize: "16px"
    fontWeight: 650
    lineHeight: 1.4
  body:
    fontFamily: "Inter, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Inter, sans-serif"
    fontSize: "12px"
    fontWeight: 400
  numeric:
    fontFamily: "JetBrains Mono, monospace"
    fontSize: "20px"
    fontWeight: 400
rounded:
  badge: "6px"
  tooltip: "8px"
  control: "12px"
  panel: "16px"
spacing:
  small: "4px"
  compact: "8px"
  control: "12px"
  panel: "16px"
  wide-panel: "20px"
  section: "24px"
  wide-gutter: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  button-default:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  text-field:
    backgroundColor: "{colors.surface2}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "12px"
  navigation-current:
    backgroundColor: "{colors.surface2}"
    textColor: "{colors.primary}"
    rounded: "{rounded.control}"
    padding: "10px 4px"
  badge:
    backgroundColor: "{colors.surface2}"
    textColor: "{colors.secondary}"
    rounded: "{rounded.badge}"
    padding: "4px 8px"
  status-normal:
    backgroundColor: "{colors.ok-bg}"
    textColor: "{colors.ok}"
    rounded: "{rounded.badge}"
    padding: "4px 6px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "16px"
---
# Design System: Jibek Joly

## Overview

**Creative North Star: "Степной свет"**

A light dispatcher workspace places white instruments on a warm cream field. Blue identifies actions and selection; restrained sand detail gives the own-brand rail mark a local visual accent. Inter keeps interface text compact while JetBrains Mono makes changing times and measurements easy to scan.

The approved world is A, “Степной свет”, with the warm ground and event telegrams from B. The user pinned the cream palette and type families; generic saturation or font detectors do not override that choice. This document records the current dispatcher implementation, not the older green/Golos laboratory.

**Key Characteristics:**
- Light by default, with a token-matched dark theme.
- Own Jibek Joly rail mark; no subtitle, organizer logo or organizer photography.
- Compact white panels, soft structural shadows and visible keyboard focus.
- Kazakhstan-only SIM context and RU/KK labels with explicit units.

The normative primitives above are extracted from `services/ai/web/dispatch.css`. The `dark-` color entries represent that file's `[data-theme=dark]` overrides, not additional accent roles. `.impeccable/design.json` adds motion, shadow, breakpoint and component-preview metadata. Surface composition is recorded in `.impeccable/surfaces/services-ai-web.md`; product boundaries are in `PRODUCT.md`.

## Colors

### Primary

**Rail blue** (`primary`) identifies actions, selected controls, focus and high-speed trains. **Sand** (`sand`) is a restrained brand ornament and text-selection fill, not a severity signal.

### Secondary

**Passenger purple** (`passenger`) and **freight brown** (`freight`) distinguish train type together with marker shape. **State green**, **state amber** and **critical red** (`ok`, `warning`, `critical`) pair with their corresponding soft backgrounds. The implemented light green and amber are darker than the original brief for legible small status text; the frontmatter records the CSS values actually shipped.

### Neutral

**Cream ground** (`bg`), **white instrument** (`surface`) and **warm secondary field** (`surface2`) establish depth. `border` separates rows and tools. `text` is primary ink; `secondary` supports readable captions and labels. `muted` exists for nonessential content and must not replace supporting text indiscriminately.

**The State Has Words Rule.** Train type uses shape, line treatment and blue/purple/brown identity; green, amber and red communicate state with words or symbols alongside color.

## Typography

Inter is locally served in Latin, Cyrillic and Cyrillic Extended subsets with weight range 100–900 and swap loading. JetBrains Mono uses matching local subsets for time, IDs, outputs, numeric facts and prediction values. The body and form controls use tabular numerals. Local font licenses remain with the assets.

The main heading uses the display role; section headings use the title role. Body text is 14px and supporting labels 12px. The brand is 20px/700, reducing to 16px in compact headers. Drawer/tour headings and the quality state use 20px; the score inside the ring is 28px mono with weight 600. At the narrow breakpoint the main heading becomes 20px. Paragraphs have a 75ch maximum width.

Kazakh glyph samples in Settings cover ә ғ қ ң ө ұ ү һ і and uppercase forms. Earlier screenshots show the glyphs, but current post-fix captures remain pending. The diagram keeps an 880px minimum canvas in a local horizontal scroller; the resize observer protects an effective 12px SVG label floor. Do not shrink the whole diagram to fit a phone.

## Layout

A sticky 56px header, fixed left navigation rail and fixed advisory footer frame the desktop workspace. The rail is 104px wide; main content starts after it with 24px gutters and a 2000px maximum width. The overview pairs a flexible map with an index/event column, followed by the diagram and train register. The baseline grid is 1.6fr / minmax(320px, 1fr) with a 16px gap. Panels use 16px padding. The train/station drawer is 420px wide, bounded by the viewport, with 24px padding.

At 1700px and above, the grid becomes 1.65fr / minmax(400px, 1fr), panel padding becomes 20px and main side gutters 32px. The final CSS override makes the map 320px high at this size. At 1400px and below the rail becomes 88px, main padding becomes 20px 16px, the map is 340px high, and the clock stacks its UTC+5 label. At 1100px and below the role and connection indicators are hidden in the topbar; the grid becomes 1.3fr / minmax(280px, 1fr), and evidence stacks.

At 760px and below the header wraps, the rail becomes a horizontally scrollable row in document flow, and content stacks with 12px side gutters. The drawer fills the width; choices and the chat form stack. The diagram's own scroll container preserves its 880px minimum width; register/table scrollers remain local. This is a responsive dispatcher, not a dedicated driver product.

## Elevation & Depth

Panels and the tour use the two-part ambient shadow defined by `--shadow`; the dark theme uses a single softer shadow. The fixed drawer has a separate directional shadow. Thin borders continue to organize tables, header, footer and controls. Exact shadow values are stored in the sidecar extensions, which are copied from the CSS.

Buttons transition transform and opacity over 160ms with the declared easing; drawer and decision entrances use a 360ms horizontal fade. The incident pulse runs at 1.5s and stops after acknowledgement. The score count-up is 360ms in JavaScript; camera incident focus is 400ms and map positions use frame interpolation. Reduced-motion preference and the explicit Settings control suppress animations; JavaScript switches to immediate updates. These describe implementation, not verified frame-rate or latency guarantees.

## Shapes

Controls and the map window use gently rounded 12px corners. Panels, incident banners and the tour use 16px corners. Badges and statuses use 6px corners; hover panels use 8px. The own brand SVG is paired with a small sand rail ornament in the wider header. Circles express station occupancy, train status and gauges. Marker shapes distinguish passenger, high-speed and freight services.

## Components

### Buttons and fields

Buttons, selects and numeric fields have a 40px minimum height, a thin border and 8px 12px padding. The primary and pressed variants use blue fill with surface-colored text. Default hover uses the secondary surface; primary hover lowers opacity to 0.9; active buttons move down 1px. Disabled controls use 0.5 opacity and the wait cursor. A 3px blue focus outline with a 3px offset is shared across keyboard targets.

The chat field uses the secondary surface, 12px padding, a 56px minimum height and vertical resizing. Native range and checkbox accents use the primary color. Labels remain associated with controls, including visually hidden labels.

### Navigation and containers

The rail uses line SVG icons above compact text. The current page receives secondary fill and blue, heavier text; it also has `aria-current`. On narrow screens it becomes a row. Panels group one instrument at a time; rows and telegram events are divided with thin rules. Badges provide context; status chips pair a symbol and readable value with semantic color.

### Linked railway views

Map markers, diagram lines, register buttons and the inspector share the selected train. Selecting it updates the next-station context. The map uses local country geometry and route vectors, with MapLibre or a selectable SVG mode. Shapes, direction arrows, selected identity and written track occupancy carry meaning alongside color. Source notes disclose approximate geometry. Map collision avoidance and leader-line code have been patched, but final rendered legibility is not yet confirmed.

The diagram separates thin timetable, bold recorded positions and dashed current-speed extrapolation. It offers station/kilometer axes, 30/60-minute tick steps, crosshair text, drag zoom, recorded-history replay and CSV export. Dashed continuation is explicitly not a solver plan. The chart's local scroller is keyboard focusable.

### Movement index, exercise and inspection

The movement ring renders the backend's transparent demo formula and point deductions with a short history sparkline. The timed incident banner is a separate two-train exercise with its own score relative to FIFO; it does not update movement on the map. Its comparison cells explicitly say when a solver result has not been calculated for that exercise. The selected A/B/C action is checked by the platform validator against the pinned exercise snapshot and displayed as accepted or rejected without applying it. A full-width planner panel on the main screen shows FIFO order and a validator-checked CP-SAT block plan for the exercise pair from a pinned map snapshot, plus the separate status of a 28-train attempt. It shows snapshot time, SIM IDs, limits and a recalculate action. Forecast loading, suppressed/unreliable values and request errors have separate written states; failed forecasts clear dependent fields and offer retry.

The drawer opens on selection, focuses its close control and restores focus to its opener when closed. It contains either train facts and model boundaries or a schematic station track view. Technical IDs and domain details sit in a disclosure. Escape closes it. The own-brand footer remains visible across app sections.

## Do's and Don'ts

### Do:
- **Do** preserve the approved cream/blue world, Inter and JetBrains Mono.
- **Do** keep Kazakhstan-only SIM context and the advisory footer visible.
- **Do** give status, unavailable data and selection a readable non-color explanation.
- **Do** retain local chart scrolling when it preserves label legibility at narrow widths.
- **Do** use local fonts, icons and map geometry; keep the own rail mark.

### Don't:
- **Don't** add English, a brand subtitle, an organizer logo or a dedicated mobile driver screen.
- **Don't** use sand as a status color or encode train type with red/amber/green.
- **Don't** present the two-train exercise score as the movement index or a solver benefit.
- **Don't** claim final visual approval, contrast compliance or the frame-rate budget from source inspection alone.
