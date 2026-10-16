const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ 
    chromeFlags: [
      '--headless',
      '--window-size=1280,800'
    ] 
  });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));
  
  const dim = await page.evaluate(() => {
    const section = document.querySelector('section[aria-label="Interactive route map"]');
    const container = document.querySelector('[data-testid="map-container"]');
    const canvas = document.querySelector('canvas');
    return {
      section: section ? { w: section.offsetWidth, h: section.offsetHeight } : null,
      container: container ? { w: container.offsetWidth, h: container.offsetHeight } : null,
      canvas: canvas ? { w: canvas.offsetWidth, h: canvas.offsetHeight } : null,
    };
  });
  console.log("Updated Dimensions:", JSON.stringify(dim, null, 2));
  
  await page.screenshot({ path: '/Users/vikaskumar0205/.gemini/antigravity/brain/516e7cb5-8e86-42bd-872b-ace1aed15c97/final-fixed-map.png' });
  console.log("Screenshot saved!");
  await browser.close();
  await chrome.kill();
})();
