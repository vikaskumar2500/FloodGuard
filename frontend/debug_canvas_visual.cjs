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

  // Screenshot specifically the canvas element
  const canvas = await page.$('canvas');
  if (canvas) {
    await canvas.screenshot({ path: '/Users/vikaskumar0205/.gemini/antigravity/brain/516e7cb5-8e86-42bd-872b-ace1aed15c97/canvas-element-screenshot.png' });
    console.log("Canvas element screenshot saved!");
  } else {
    console.log("Canvas not found!");
  }

  // Screenshot the map section element
  const section = await page.$('section[aria-label="Interactive route map"]');
  if (section) {
    await section.screenshot({ path: '/Users/vikaskumar0205/.gemini/antigravity/brain/516e7cb5-8e86-42bd-872b-ace1aed15c97/section-element-screenshot.png' });
    console.log("Section element screenshot saved!");
  }

  await browser.close();
  await chrome.kill();
})();
