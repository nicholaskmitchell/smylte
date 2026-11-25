// Screenshots of preview.html with Playwright (headless Chromium), 1400 × 900.
// The page and parts.json are served from disk by request interception (origin http://rev-e.local);
// three.js r128 comes from cdnjs through the session's HTTPS proxy, if one is set.
const path = require('path'); const fs = require('fs');
const { chromium } = require('/home/user/smylte/frontend/node_modules/playwright');
const ROOT = path.resolve(__dirname, '..');
const TYPES = {'.html':'text/html', '.json':'application/json', '.js':'text/javascript'};
const SHOTS = [
  ['front-three-quarter', v => v.set(0.62, 1.25, 430)],
  ['side', v => v.set(Math.PI / 2, 1.5708, 400)],
  ['rear-three-quarter', v => v.set(Math.PI - 0.7, 1.18, 430)],
  ['exploded', v => { v.explodeNow(true); v.set(1.3, 1.25, 1000, [0, 95, 70]); }],
  ['shell-off', v => { v.explodeNow(false); v.set(1.62, 1.3, 440, [0, 60, 33]); v.shell(true); }],
  ['bottom', v => { v.shell(false); v.set(0.35, 2.75, 430); }],
];
(async () => {
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    proxy: proxy ? { server: proxy } : undefined });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  await page.route('http://rev-e.local/**', route => {
    const p = path.join(ROOT, decodeURIComponent(new URL(route.request().url()).pathname));
    if (!p.startsWith(ROOT) || !fs.existsSync(p)) return route.fulfill({ status: 404, body: '' });
    route.fulfill({ status: 200, contentType: TYPES[path.extname(p)] || 'application/octet-stream', body: fs.readFileSync(p) });
  });
  page.on('console', m => { if (m.type() === 'error') console.log('console:', m.text()); });
  await page.goto('http://rev-e.local/preview/preview.html');
  await page.waitForFunction(() => window.__ready !== undefined, null, { timeout: 120000 });
  if (await page.evaluate(() => window.__ready) !== true) throw new Error('preview failed to load');
  for (const [name, fn] of SHOTS) {
    await page.evaluate(`(${fn.toString()})(window.__view)`);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(__dirname, `${name}.png`) });
    console.log('wrote', name + '.png');
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
