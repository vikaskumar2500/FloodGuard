const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));

  const mapDetails = await page.evaluate(() => {
    // Look for maplibregl instance on window or container
    const container = document.querySelector('[data-testid="map-container"]');
    // MapLibre attaches map to container or internal property
    return {
      innerHTML: container ? container.innerHTML.slice(0, 500) : null,
      childNodesCount: container ? container.childNodes.length : 0,
      classes: container ? container.className : null
    };
  });
  console.log("Map container details:", JSON.stringify(mapDetails, null, 2));

  await browser.close();
  await chrome.kill();
})();
