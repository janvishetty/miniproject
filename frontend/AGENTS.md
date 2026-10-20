# figma-make-app

React + Vite + Tailwind CSS project running inside Figma Make.

## Development Server

A Vite development server is **already running** on `$PORT` (default 8443). You don't need to start it manually.

- Preview URL: The user can access the running app through the preview panel
- Hot reload: Changes to source files are reflected immediately

## Project Structure

This is the canonical project structure. Start with task-relevant files below. Only follow imports or inspect other files when required, when a documented path is missing, or when the repository contradicts this guide.

- `src/main.tsx` - React entrypoint; imports `src/index.css` and mounts `src/App.tsx` into the `#root` element
- `src/App.tsx` - Primary application component and the usual starting point for UI work
- `src/index.css` - Global CSS entrypoint and Tailwind CSS v4 import
- `index.html` - Vite HTML shell containing the `#root` element and loading `src/main.tsx`
- `package.json` - Project dependencies and the Vite build, development, preview, and formatting scripts
- `vite.config.ts` - Vite configuration with React, Tailwind CSS v4, and Figma Make plugins plus the `@` alias for `src`
- `.mise.toml` - Toolchain versions for Node.js and pnpm

## Dependencies

- Runtime: React 19 and React DOM 19
- Styling: Tailwind CSS v4 with the `@tailwindcss/vite` plugin
- Build tooling: Vite 8, TypeScript 5.7, and `@vitejs/plugin-react`
- Formatting: oxfmt

## Styling

This project uses **Tailwind CSS v4** through the `@tailwindcss/vite` plugin configured in `vite.config.ts`. `src/index.css` imports Tailwind with `@import 'tailwindcss';`. Use Tailwind utility classes directly in JSX and put global CSS or Tailwind v4 theme customization in `src/index.css`. This scaffold does not need a Tailwind config file or PostCSS config.

`src/main.tsx` imports `src/index.css`, so global font wiring belongs in `src/index.css`. Keep CSS `@import` statements first, then add any `@font-face` rules and font-family defaults there.

## Code quality

- Use double quotes for strings containing apostrophes (`"We're here to help"`), or escape them in single-quoted strings. An unescaped apostrophe in a single-quoted string breaks the build.
- Ensure JSX tags are closed and braces are balanced.
- Export components as default exports.

## Project conventions (this repo)

These apply on top of the scaffold notes above. Full details are in the root `README.md`, section "Frontend".

- Style with the tokens in `src/theme.ts` (`t.*`) and the components in `src/ui.tsx` and `src/charts.tsx`, passed the theme as `t`. Do not add new colours, styles or libraries; the scaffold's Tailwind advice applies to `src/index.css` only.
- Token roles: `t.blue` is accent text, `t.accent` an accent fill, `t.primary` a button fill, the `*Fill` tokens and `t.accentGrad` are for bars and dots, `t.link` is the neutral accent (ids, links), `t.sel*` the selected state.
- Both themes (LIGHT and DARK) must stay readable: text at least 4.5:1. Keep keyboard focus rings and the reduced-motion and reduced-transparency rules in `src/index.css`.
- The Report detail page prints as one plain column: keep the classes `no-print`, `report-aside`, `report-print-root`, `report-container` and `report-row`, and the print rules in `ReportDetailPage.tsx`. Do not add wrapper elements around the app root or the nav (the print rules select them).
- The app has no router; the only deep link is `#report=INC-YYYY-NNNN`.
