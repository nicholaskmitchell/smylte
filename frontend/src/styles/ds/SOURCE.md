# Design-system files, copied verbatim

These two files are the N.K.M. design system's runtime tokens for app surfaces
("Field notes", Nov 2026). They are copied byte for byte from the design system
artifact and are never edited here: a change to the look is made in the design
system and copied in again.

| File | Source path in the design system | sha256 |
|---|---|---|
| `themes.css` | `project/tokens/themes.css` | `7587482214b1547a1eb09f49a5deeb59e4eaebcbfe723a7d5bbcec36edcff071` |
| `app-motion.css` | `project/tokens/app-motion.css` | `299ddb0d09d0d21762d2dd912c437ceb7b2cd130ecd4909543bbb204a91657a1` |

Source: https://claude.ai/artifact/UwhQnjyUvfDnE3TTKC6erb (version 1794854056-bd30).

`src/fieldnotes-tokens.test.ts` pins both hashes, so an edit made here instead of
in the design system fails the build. To take a new version, copy both files,
update the hashes in this table and in that test, and run the suites.

How the repo uses them:

- Field notes is on when `<html data-surface="app">` is set, and off while a
  preset (Classic, Workspace, the Sep 2026 design) is active, so a preset renders
  exactly as it did before Field notes existed.
- They load before `tokens.css` (see `main.tsx`). Field notes values win by
  specificity, not order; loading first lets the repo's own Workspace blocks,
  which restate every property, shadow the design system's copy of Workspace.
- `data-accent` is never set in Smylte, so the Søren blocks stay inert.
