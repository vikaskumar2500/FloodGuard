const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ 
    chromeFlags: [
      '--headless',
      '--window-size=1440,900'
    ] 
  });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));

  // Screenshot with zoom in on Mumbai
  await page.evaluate(() => {
    // Click zoom in button twice
    const zoomIn = document.querySelector('.maplibregl-ctrl-zoom-in');
    if (zoomIn) {
      zoomIn.click();
      zoomIn.click();
    }
  });

  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: '/Users/vikaskumar0205/.gemini/antigravity/brain/516e7cb5-8e86-42bd-872b-ace1aed15c97/zoomed-map-mumbai.png' });
  console.log("Zoomed screenshot saved!");

  await browser.close();
  await chrome.kill();
})();
