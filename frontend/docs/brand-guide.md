# Aeza brand guide: interface implementation

Source: user-provided `Аеза_Гайдбук_2026.pdf`, 43 pages. Page references below use physical PDF pages (the printed section divider numbers occasionally differ).

## Palette

- Primary (page 15): sky blue `#4CC6F1`, black `#000000`, light gray `#F4F4F4`. Blue is the main brand accent; black is used for typography, graphics, and backgrounds; gray provides structure and secondary surfaces. White is shown in approved logo and interface artwork.
- Supporting accents (page 16): pink `#ECCFDB`, navy `#182D48`, orange `#E97C35`. Use sparingly in interfaces and supporting graphics.
- Remove the previous decorative mint, purple, and teal palette. Transparency of approved colors can provide quiet secondary surfaces without introducing a different accent family.
- Explicit product exception requested by the user: destructive/reset controls retain the same semantic red as cancellation (`--red: #a52936`, with the existing red background/border). This is an interaction/error color, not a replacement brand accent. Reset, cancellation, errors, and overdue states must also have text/icon cues rather than rely on color alone.

## Typography

- Exo 2 is the primary family for headings, body copy, interfaces, and key communications (page 18).
- Inter is the supplementary family for short labels, captions, explanations, and information blocks (page 19). “Inter 18pt” identifies the font shown in the PDF; it is not a requirement to make all web text 18 pt.
- The PDF demonstrates Exo 2 Black and Regular, Inter 18pt Regular and Black. It does not prescribe a complete web type scale, line height, tracking, or all allowed weights. A readable web scale and other available family weights are implementation choices.
- Use full licensed font files with Cyrillic support, preferably self-hosted. Embedded PDF fonts are subsets and must not be treated as complete web fonts.

## Logo

- The primary mark is four keycaps in the fixed `a é z a` arrangement (pages 6-8). The compact approved alternative is the original `é` keycap (page 10).
- Approved variants are monochrome: white on black and black on white (pages 11 and 13). Do not recolor the mark with the blue accent.
- Keep a clear area around the logo; the page 9 diagram specifies 30 px. No decorative receipt badge, text, or line should overlap this area.
- Do not distort, rotate, skew, outline, add glow/shadow, recolor, rearrange, or independently animate the logo parts (page 12). App icon artwork on page 13 shows presentation shadows, but the stricter logo prohibition is used for the interface mark.
- Existing hover disclosure can keep the original mark fixed and reveal the separate product name beyond the clear area. Do not morph the letter into a newly drawn word or animate individual keycaps.
- `public/brand/aeza-mark-light-on-dark.png` is the original compact mark cropped from page 10, rendered at 4x (1392 x 1392), with only the external page background made transparent. `aeza-mark-dark-on-light.png` is its approved monochrome inversion, matching pages 11 and 13. Glyph shape and keycap proportions are retained; neither uses a typeset replacement `é`.
- Display at a square aspect ratio with `object-fit: contain`; do not add another border, badge, shadow, glow, or CSS color filter. Keep the relevant monochrome tile visible on a contrasting surrounding surface.

## Icons and decoration

- Interface/navigation icons are solid filled silhouettes with rounded corners (page 21). Outline-only Lucide icons do not match this requirement; use a consistent filled icon set, keeping essential interior cutouts legible.
- The brand pattern is three straight parallel lines plus a contrasting accent line which follows them before turning with a smoothly rounded corner (page 22). Use low contrast behind content or contained in decorative panels; it must not obscure controls or data.
- The document specifies no general UI radius scale, grid, card border, gradient prohibition, or motion timings. Rounded cards, accessible controls, responsive layouts, and restrained transitions are product decisions. For strict visual alignment, prefer the flat palette and approved line pattern rather than introducing decorative multicolor gradients.
- There is no general ban on UI animation. Preserve meaningful button, drawer, page, and field transitions; respect `prefers-reduced-motion`. Logo transformations listed above remain prohibited even when animated.
- The mascot (pages 23-24) and merchandise examples (pages 25-43) are intentionally excluded at the user's request. Apply these interface rules to the login screen as well.

## Later user-directed application details

The user subsequently requested the approved keycap presentation with a circular receipt badge, matching their app-icon reference. The small separate badge is an explicit exception to the earlier no-badge interpretation; the original glyph is not redrawn, rotated or distorted. Light/dark monochrome keycaps are switched with the website theme.

The site theme offers Light, Dark and System choices, remembers the preference locally, follows operating-system changes in System mode, and respects reduced motion. The general ban on mascot and merchandise remains in effect.
