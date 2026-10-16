const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  const rules = await page.evaluate(() => {
    let hasMaplibre = false;
    for (const sheet of document.styleSheets) {
      try {
        for (const rule of sheet.cssRules) {
          if (rule.selectorText && rule.selectorText.includes('maplibregl')) {
            hasMaplibre = true;
            return { found: true, sample: rule.cssText };
          }
        }
      } catch (e) {}
    }
    return { found: false };
  });
  console.log("Maplibre CSS loaded in browser:", rules);
  await browser.close();
  await chrome.kill();
})();
