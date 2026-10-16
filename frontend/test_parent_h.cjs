const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  const res = await page.evaluate(() => {
    const mapContainer = document.querySelector('[data-testid="map-container"]');
    return {
      mapContainer: {
        offsetHeight: mapContainer.offsetHeight,
        clientHeight: mapContainer.clientHeight,
        getBoundingClientRect: mapContainer.getBoundingClientRect()
      },
      mapCanvasContainer: {
        offsetHeight: mapContainer.firstElementChild ? mapContainer.firstElementChild.offsetHeight : null,
        clientHeight: mapContainer.firstElementChild ? mapContainer.firstElementChild.clientHeight : null,
      }
    };
  });
  console.log("Heights:", JSON.stringify(res, null, 2));
  await browser.close();
  await chrome.kill();
})();
