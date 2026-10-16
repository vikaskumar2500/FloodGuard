const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  const rules = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="map-container"]');
    const s = window.getComputedStyle(el);
    return {
      position: s.position,
      top: s.top,
      bottom: s.bottom,
      left: s.left,
      right: s.right,
      height: s.height,
      width: s.width
    };
  });
  console.log("data-testid computed:", rules);
  await browser.close();
  await chrome.kill();
})();
