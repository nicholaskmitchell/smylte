/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import { configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Dev: `npm run dev` proxies API calls to the FastAPI app on :8080.
// Build: `npm run build` emits dist/, which FastAPI serves statically.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/internal': 'http://127.0.0.1:8080',
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
  // TWO test projects, because they disagree about the one setting that matters.
  //
  // `unit` is the whole existing suite and is unchanged. `browser` exists because
  // that suite computes NO LAYOUT: jsdom applies none, `css: false` stubs the
  // stylesheets, and no media query is ever evaluated. Four times now a rule
  // written into `@media (max-width: 720px)` has shipped dead — beaten by a later
  // declaration at equal specificity — with every one of the 1000-odd tests green,
  // and the only thing that has ever caught one is opening Chromium at 390px and
  // measuring. That is what the second project does.
  //
  // They cannot share a `test` block: the browser project's entire value is real
  // CSS in a real cascade, and `css: false` is global.
  test: {
    projects: [
      {
        extends: true,          // plugins/resolve from the config above
        test: {
          name: 'unit',
          environment: 'jsdom',
          globals: true,        // lets testing-library auto-cleanup between tests
          setupFiles: './src/test/setup.ts',
          // Pin the clock's zone. CI runs on ubuntu-latest, which is UTC — a zone
          // with no DST, where a daylight-saving bug in the calendar math cannot
          // fail a test however the test is written. Two of the findings in #32
          // were exactly that. New York observes DST and every suite passes under
          // it.
          env: { TZ: 'America/New_York' },
          // Stylesheets are stubbed — nothing in THIS project asserts on rendered
          // styles, and processing them is pure cost. Note this defeats `?raw` on
          // .css too, so appearance.test.ts reads tokens.css off disk rather than
          // importing it.
          css: false,
          // Without this the default include glob (`**/*.test.tsx`) swallows the
          // browser files and runs them under jsdom, where every box is 0x0 and
          // every assertion in them is a false negative.
          exclude: [...configDefaults.exclude, '**/*.browser.test.tsx'],
        },
      },
      {
        extends: true,
        test: {
          name: 'browser',
          globals: true,
          // NOT src/test/setup.ts. That file's whole job is a hand-written
          // `matchMedia` stub, and a real browser must be allowed its own — the
          // media queries are half of what is under test here.
          setupFiles: './src/test/browser-setup.ts',
          include: ['src/**/*.browser.test.tsx'],
          browser: {
            enabled: true,
            provider: 'playwright',
            headless: true,
            instances: [{
              browser: 'chromium',
              // `env: { TZ }` above is a NODE process variable and never reaches
              // the page, so the zone has to be set on the browser context or the
              // DST pinning the comment above defends is silently lost here.
              context: { timezoneId: 'America/New_York' },
            }],
          },
        },
      },
    ],
  },
})
