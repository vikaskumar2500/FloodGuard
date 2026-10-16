const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless', '--window-size=1280,800'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  // Set coordinates to seed coordinates
  await page.evaluate(() => {
    const inputs = document.querySelectorAll('input[type="text"], input[type="number"]');
    // let's find the inputs
  });
  
  await page.screenshot({ path: '/Users/vikaskumar0205/.gemini/antigravity/brain/516e7cb5-8e86-42bd-872b-ace1aed15c97/seeded-map-ui.png' });
  console.log("Screenshot taken");
  await browser.close();
  await chrome.kill();
})();
