const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  
  page.on('response', res => {
    if (res.url().includes('cartocdn') || res.url().includes('openstreetmap') || res.url().includes('demotiles')) {
      console.log('TILE RESPONSE:', res.status(), res.url());
    }
  });

  console.log("Navigating to localhost:3000...");
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  await new Promise(r => setTimeout(r, 4000));
  
  await browser.close();
  await chrome.kill();
})();
