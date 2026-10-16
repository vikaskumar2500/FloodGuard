const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless', '--window-size=1280,800'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  const info = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return { error: "No canvas found!" };
    const rect = canvas.getBoundingClientRect();
    const style = window.getComputedStyle(canvas);
    return {
      width: canvas.width,
      height: canvas.height,
      rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
      display: style.display,
      visibility: style.visibility,
      opacity: style.opacity,
      parentHtml: canvas.parentElement ? canvas.parentElement.className : null
    };
  });
  console.log("Canvas info:", JSON.stringify(info, null, 2));
  
  await browser.close();
  await chrome.kill();
})();
