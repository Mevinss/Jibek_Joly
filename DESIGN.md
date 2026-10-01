---
name: TurkiSib
description: Russian-language railway scenario workbench for an advisory ML demo.
colors:
  paper: "#f3f2ec"
  white: "#fffefa"
  ink: "#182925"
  muted: "#58655e"
  line: "#d5d9ce"
  green: "#146b50"
  lime: "#dbea8b"
  wash: "#eaf0e5"
  amber: "#895019"
  error: "#9b3029"
  inspector: "#f8f9f3"
  track: "#dce3d6"
  green-hover: "#0d523d"
  button-text: "#ffffff"
typography:
  display:
    fontFamily: "Golos, system-ui, sans-serif"
    fontSize: "clamp(26px, 3vw, 40px)"
    fontWeight: 550
    lineHeight: 1.18
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Golos, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 550
    lineHeight: 1.35
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Golos, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 550
    lineHeight: 1.55
  body:
    fontFamily: "Golos, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Golos, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.55
  caption:
    fontFamily: "Golos, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.6
  result:
    fontFamily: "Golos, system-ui, sans-serif"
    fontSize: "46px"
    fontWeight: 550
    lineHeight: 1.15
    letterSpacing: "-0.04em"
rounded:
  bar: "2px"
  compact: "4px"
  control: "8px"
  container: "12px"
spacing:
  small: "8px"
  control: "12px"
  medium: "16px"
  panel: "20px"
  section: "24px"
  gutter: "28px"
components:
  button-primary:
    backgroundColor: "{colors.green}"
    textColor: "{colors.button-text}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  button-primary-hover:
    backgroundColor: "{colors.green-hover}"
  button-default:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "5px"
  search-field:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
    width: "150px"
  tag:
    backgroundColor: "{colors.wash}"
    textColor: "{colors.green}"
    rounded: "{rounded.compact}"
    padding: "3px 9px"
  workbench:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.container}"
  train-marker:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.compact}"
    padding: "4px 2px"
  train-marker-selected:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.ink}"
    rounded: "{rounded.compact}"
    padding: "4px 2px"
---

# Design System: TurkiSib

## Overview

**Creative North Star: "Railway engineering test bench"**

An off-white instrument surface, evergreen ink and restrained lime selection support a compact Russian-language analysis workspace. Rules divide related information; controls and measured results sit together without decorative elevation. The visual hierarchy gives the forecast number prominence while keeping its units and limitations nearby.

This is a record of the built FastAPI-served interface in `services/ai/web`, not a future specification. The user delegated visual decisions; no explicit approval of a design direction is claimed. The Replicate reference informed separation of input and output, while TurkiSib uses its own palette and component shapes. Surface composition and direction history remain in `.impeccable/surfaces/services-ai-web.md`.

**Key Characteristics:**
- Flat, ruled surfaces with a darker instrument masthead.
- One locally served Cyrillic-capable type family and tabular numerals.
- Linked train selection across route markers, register and inspector.
- Visible model, heuristic, busy and failure states with explicit units.

## Colors

Warm paper neutrals provide the field; green carries actions and model output, while lime locates the current selection.

### Primary
- **Evergreen** (`green`): primary actions, heading accent, range controls, focus, model curves and ordinary risk values. `green-hover` is the primary-button hover state.
- **Selection lime** (`lime`): selected train marker, current chart point, brand mark, connection text, text selection and skip-link background.

### Secondary
- **Warning amber** (`amber`): values above the configured threshold, positive feature contributions and heuristic notes. It communicates a state, not a second action hierarchy.
- **Error red** (`error`): request-failure text. The error panel also uses its existing pale warm fill and border, carried in the sidecar example.

### Neutral
- **Paper** (`paper`): page field and sticky table headings.
- **Warm white** (`white`): workbench, conversation and form controls; primary button text uses the separate pure-white token already in CSS.
- **Evergreen ink** (`ink`): body text, masthead, station discs and current-point outline.
- **Muted ink** (`muted`): supporting labels and explanations.
- **Rule** (`line`): panel borders, section separators and chart grid.
- **Selection wash** (`wash`): selected register row, tags, user messages and ordinary button hover.
- **Inspector tint** (`inspector`): the model inspector within the continuous workbench.
- **Track** (`track`): unfilled risk and contribution bars.

**The State Has Words Rule.** Selection uses pressed state as well as fill; risk, heuristic and failure states retain textual explanations alongside color.

## Typography

Golos is the display and body face, served from `/fonts/GolosText.ttf` with `font-display: swap` and the declared weight range 400–900. The repository includes the Google Fonts OFL license. System UI and sans-serif are fallbacks, not an alternative display identity. No shipping raster images are used; the brand and plots are vector or CSS elements.

The type is compact and legible, with moderate heading weight and tightened display tracking. Frontmatter records the base hierarchy. The page heading becomes 30px at the narrow breakpoint; evidence headings are 16px. The chat introduction uses 26px and the explanatory heading 28px, both reducing to 25px on smaller layouts. Paragraphs have a maximum width of 72ch. Conversation text is 13px; table values are 12px, reducing to 11px on narrow screens. Tags use 11px/500 with 0.015em tracking.

**The Stable Numbers Rule.** Buttons, tags, outputs, tables, forecast values, risk rows and chart keys use tabular numerals; Russian number formatting and explicit minutes or percentages remain visible.

## Layout

The main container is centered with a maximum width of 1440px and base padding of 34px 28px 0. The workbench joins a flexible dispatch region and a 350px inspector with a single border; both have 24px internal padding. Section spacing is context-specific, using recurring 8, 12, 16, 20, 24 and 28px steps rather than claiming an exclusive mathematical scale.

At 1100px and below the inspector becomes 310px and panel padding becomes 20px. At 800px and below the inspector follows the register, with its form and output temporarily in two columns; navigation occupies a second masthead row. Main side gutters become 18px. At 540px and below the inspector, evidence, chat introduction and explanation stack; scenario controls form one column and the chat submit button spans the width. The chart's internal label size becomes 19px in its 620-unit SVG viewBox to remain readable when scaled down.

The register intentionally scrolls within its own container. Its narrow layout preserves a 410px minimum table width and a 265px maximum scroll height, so columns retain their meaning through local horizontal scrolling. The ordinary scroll height is 356px, increasing to 360px at 1550px. This is not page-wide overflow.

## Elevation & Depth

The built interface uses no box shadows. Tonal fields, thin rules and whitespace separate the paper page, warm-white workspace and tinted inspector. A sticky table header is functional layering, not a floating card treatment. The global keyboard-focus outline is 3px evergreen with a 4px offset.

**The Ruled Surface Rule.** Keep related regions continuous and separate them with borders or background tones; do not add shadows to existing panels.

The risk fill transitions its horizontal scale over 0.35s using `cubic-bezier(.16,1,.3,1)`. Smooth anchor scrolling is the other deliberate motion. Reduced-motion preference disables transitions and animation and changes scrolling to immediate movement. Values and state labels remain understandable without motion.

## Shapes

Controls and user messages use the control radius; larger workspace and conversation containers use the container radius. Tags and train markers use the compact radius, while risk and contribution bars use the bar radius. Circles belong to station discs, plotted points and small state indicators. Borders are generally 1px. These circles are meaningful schematic marks, not a mandate to turn controls into pills.

## Components

### Buttons

Primary buttons are filled evergreen with pure-white, 12px/500 text. Standard buttons are warm white with a rule border and inherit body typography. Both use 10px 14px padding and a 42px minimum height; chat submission uses 44px. Quiet actions have an underline, transparent background, no border, 5px padding and a 32px minimum height. Disabled buttons use a wait cursor and 0.55 opacity. Every variant retains the global visible-focus outline.

### Inputs / Fields

Search, numeric fields, selects and the chat textarea use warm-white fill, a rule border and the control radius. Search is 150px wide with 8px 12px padding, reducing to 120px on narrow screens. Select padding leaves room for the native indicator. Range sliders and checkboxes use evergreen native accents. Numeric validation uses the browser's validity feedback. The chat textarea resizes vertically between 66px and 160px; labels remain associated even when visually hidden.

### Navigation

The evergreen-ink masthead combines an inline SVG brand mark, text links and a textual connection status. Navigation is 13px with 24px gaps; hover turns links lime and keyboard focus remains outlined. It has no persistent selected-tab style. On smaller screens links occupy a full-width row.

### Tags

Tags are compact, non-interactive wash-filled labels for sandbox, model and version context. They use green text, 3px 9px padding and compact corners. Heuristic mode changes the label to “Правило · не ML”; the written distinction must remain.

### Containers and register

The workbench is a continuous bordered panel with an inspector division. The conversation uses the same container radius and border with 20px padding, reducing to 16px on narrow screens. The register uses sticky paper-colored column headers, right-aligned numeric columns and a wash-filled selected row. Train identifiers are real buttons with pressed state, and rerendering restores focus to the selected control.

### Linked train markers

Route markers are compact warm-white buttons, at least 28px tall. The selected marker becomes lime with a green border and 650 weight; warning markers have a small amber dot. Route and register choices update the same inspector. The schematic explicitly describes a demonstration snapshot, not a running simulation.

### Forecast and evidence

The forecast pairs a large tabular delay with a compact unit label. The risk bar has an independent threshold tick and written threshold status. The sensitivity plot uses a green line, amber dashed threshold and lime current point. Contribution bars pair signed numbers with direction color; the explanation identifies pre-calibration classifier log-odds rather than causal effects or percentage points. Data comes from actual requests; pending, unavailable and rule-based output have visible labels.

### Chat and failures

User messages use a wash-filled compact container; assistant text sits directly on the warm-white conversation surface. Speaker and scenario context identify the response. A request failure has a warm error panel with `role="alert"`; chat failure messages remain in the conversation. Initial, empty and busy states use plain Russian explanations. Snapshots, forecasts and units must remain attributable to the displayed scenario.

## Do's and Don'ts

### Do:
- **Do** keep Russian labels, explicit units and model limitations adjacent to the values they explain.
- **Do** preserve tabular numerals, visible keyboard focus and reduced-motion behavior.
- **Do** link route, table and inspector selection through both visual state and accessible pressed state.
- **Do** retain local table scrolling on narrow screens so numeric column relationships survive.

### Don't:
- **Don't** present demonstration inputs as live train control or heuristic output as ML.
- **Don't** rename the legacy next-segment proxy as a validated 15-minute conflict probability.
- **Don't** add decorative shadows or replace the local Golos display face with a system-font identity.
- **Don't** turn SHAP bars into causal claims or percentage-point contributions.

Source of truth: `services/ai/web/style.css` for tokens and responsive rules, `index.html` for component structure and Russian copy, and `app.js` for selected, pending, failure, heuristic and plotted-data states. The sidecar's synthesized tonal ramps are preview metadata, not extra shipped palette tokens. Existing arrow glyphs in the chat shortcut and API link are not canonized as an icon system; they are retained implementation debt outside this documentation-only pass.
