# GitHired site brand assets

Source kit: `assets/githired_brand_assets.zip` (raster masters).

## Production website files

| Asset | Role |
| --- | --- |
| `githired-logo-light.webp` (+ `.png`) | Combined lockup for light backgrounds (desktop nav) |
| `githired-logo-dark.webp` (+ `.png`) | Combined lockup for dark backgrounds |
| `githired-logo-*-nav.webp` | Nav-sized lockups (~80px tall for 2×) |
| `githired-mark-{128,256,512,1024}.webp` | Standalone G for compact nav / srcset |
| `favicon.ico`, `favicon-32x32.png` | Browser favicon |
| `apple-touch-icon.png` | 180×180 |
| `android-chrome-192x192.png` / `512x512.png` | PWA / Android icons |

Kit originals (`mark-transparent.png`, `icon-*.png`, etc.) are retained as masters.

## Native resolution limit

The G mark in the kit is only ~166–174px of content (even `icon-512.png` is the same art padded). WebPs larger than that are LANCZOS upscales for convenience, not new detail. Nav at 36px CSS is sharp on 2× with the 128/256 marks. A higher-resolution original or professional vector is still recommended for large hero/marketing use.
