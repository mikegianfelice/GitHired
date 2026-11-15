# GitHired site brand assets

Source kit: `assets/githired_brand_assets.zip` (raster masters + `tokens.css`).

## Site usage

| Asset | Role |
| --- | --- |
| `mark.svg` | Standalone G — favicon companion, compact/mobile nav, app-icon shape |
| `mark-solid.svg` | Flat single-color G for tiny sizes |
| `lockup-light.svg` / `lockup-dark.svg` | Mark + wordmark vectors (exports / embeds) |
| `wordmark-light.svg` / `wordmark-dark.svg` | Lettering-only vectors |
| `icon-*.png`, `favicon.ico`, `apple-touch-icon.png` | Browser / PWA icons from the kit |
| `tokens.css` | Upstream light-first tokens (also mirrored in `site/styles.css`) |

The live header composes `mark.svg` + a CSS wordmark (`Git` near-black, `Hired` deep green) so web fonts apply. Mobile hides the wordmark and keeps the G. The footer uses the wordmark alone.

Light SVG wordmarks use near-black “Git” (not white) so lettering stays readable on white.
