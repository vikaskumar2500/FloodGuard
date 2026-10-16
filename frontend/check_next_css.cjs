const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  
  const cssUrls = [];
  page.on('response', res => {
    if (res.url().includes('.css')) {
      cssUrls.push(res.url());
    }
  });

  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  console.log("Loaded CSS URLs:", cssUrls);
  await browser.close();
  await chrome.kill();
})();
