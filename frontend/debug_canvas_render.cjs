const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 2000));
  
  const debug = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return 'No canvas';
    
    // Check if webgl canvas is actually being drawn to
    // By checking pixels at a grid across the canvas
    const w = canvas.width;
    const h = canvas.height;
    return {
      width: w,
      height: h,
      styleWidth: canvas.style.width,
      styleHeight: canvas.style.height
    };
  });
  console.log("Canvas debug:", debug);
  await browser.close();
  await chrome.kill();
})();
