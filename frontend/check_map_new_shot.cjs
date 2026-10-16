const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ 
    chromeFlags: [
      '--headless',
      '--window-size=1280,800',
      '--enable-webgl',
      '--ignore-gpu-blocklist'
    ] 
  });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));
  await page.screenshot({ path: '/Users/vikaskumar0205/.gemini/antigravity/brain/516e7cb5-8e86-42bd-872b-ace1aed15c97/map-rendered-fixed.png' });
  
  const dim = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="map-container"]');
    const canvas = document.querySelector('canvas');
    return {
      el: { w: el.offsetWidth, h: el.offsetHeight },
      canvas: { w: canvas.offsetWidth, h: canvas.offsetHeight }
    };
  });
  console.log("New Dimensions:", dim);
  await browser.close();
  await chrome.kill();
})();
