const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless', '--window-size=1280,800'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  const layerInfo = await page.evaluate(() => {
    // Look at all elements overlapping the canvas
    const canvas = document.querySelector('canvas');
    if (!canvas) return "No canvas";
    const rect = canvas.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const elementsAtPoint = document.elementsFromPoint(cx, cy);
    return elementsAtPoint.map(el => `${el.tagName}.${el.className} (id: ${el.id})`);
  });
  console.log("Elements at center:", layerInfo);
  await browser.close();
  await chrome.kill();
})();
