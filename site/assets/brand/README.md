# GitHired brand assets

Source: user-provided JPEG. Assets were extracted from the raster reference, not redrawn as vectors. Transparent edges may contain minor JPEG artifacts. Do not treat these as production-quality SVG masters.

## Files
- `mark-transparent.png`: standalone G mark
- `wordmark-transparent.png`: GitHired lettering only
- `lockup-transparent.png`: original mark + lettering
- `*-dark.png`, `*-light.png`: versions on dark/light backgrounds
- `icon-{size}.png`: square transparent icons, 16–512px
- `favicon.ico`: multi-size browser icon
- `tokens.css`: light-first design tokens

## Suggested usage
Use the original green mark on white with near-black text. NOTE: The supplied wordmark uses white 'Git', so the original wordmark/lockup PNG is not readable on white. For a light theme, replace the white 'Git' letters with near-black in a vector redraw before deployment. `*-light.png` are reference previews, not finished accessible light-theme wordmarks.

Palette: green #65E52B, hover #43C91E, deep #168A43, background #FFFFFF, surface #F8FAF8, text #0B0F14, muted #647067, border #E3EAE2.

Recommended next step: trace the mark into an original SVG and recreate wordmark with a licensed font; export separate light and dark vector lockups.
