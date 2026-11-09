# Fonts for expectrail.tech

Unmodified fonts, repackaged as WOFF by compression only. Every table is byte for byte the same as in
the source font; for TeX Gyre Adventor the one exception is the `head` table's whole-file checksum,
which any repackaging recomputes. No glyphs, names, metrics or timestamps changed:

| File | Font | Licence |
| --- | --- | --- |
| `texgyreadventor-regular.woff`, `texgyreadventor-bold.woff` | TeX Gyre Adventor 2.x (GUST e-foundry) | [GUST Font License](GUST-FONT-LICENSE.txt) |
| `Lora-Variable.woff`, `Lora-Italic-Variable.woff` | Lora (The Lora Project Authors) | [SIL Open Font License 1.1](OFL-Lora.txt), Reserved Font Name "Lora" |

The source files, so the conversion can be checked: with fontTools, `TTFont(src).reader[tag]` equals
`TTFont(woff).reader[tag]` for every table (apart from the checksum noted above).

| WOFF | Converted from | SHA-256 of the source |
| --- | --- | --- |
| `texgyreadventor-regular.woff` | `texgyreadventor-regular.otf`, TeX Gyre Adventor 2.501 (Debian `fonts-texgyre` 20180621) | `ee265c1c9728be9491c7f0d7fcdcb2f97bc35040a6dc1f9815265cee333e155b` |
| `texgyreadventor-bold.woff` | `texgyreadventor-bold.otf`, the same release | `e373ae29c808c6d9149e3add46564f9acdb6ebfcd0ee311f6a55560226994720` |
| `Lora-Variable.woff` | `Lora-Variable.ttf`, Lora 3.008 (Google Fonts) | `822a6621ccbe8d97d20ac88c1c41f5615c9c2c202eaa75f272cd452aac6475a7` |
| `Lora-Italic-Variable.woff` | `Lora-Italic-Variable.ttf`, Lora 3.008 (Google Fonts) | `22d8d8854b53807aa664ca34f2031a9ed57a1d0dea296b8b96cdd3aad937a2b3` |

The logo's wordmark is drawn from TeX Gyre Adventor Bold outlines (`docs/brand/`).
