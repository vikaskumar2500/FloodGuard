const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  const css = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return "No canvas";
    const s = window.getComputedStyle(canvas);
    return {
      position: s.position,
      top: s.top,
      left: s.left,
      width: s.width,
      height: s.height,
      zIndex: s.zIndex
    };
  });
  console.log("Canvas computed CSS:", css);
  await browser.close();
  await chrome.kill();
})();
