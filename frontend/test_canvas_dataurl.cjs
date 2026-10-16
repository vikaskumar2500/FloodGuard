const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');
const fs = require('fs');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 3000));
  
  const dataUrl = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    return canvas ? canvas.toDataURL() : null;
  });
  console.log("DataURL prefix:", dataUrl ? dataUrl.slice(0, 50) : null);
  console.log("DataURL length:", dataUrl ? dataUrl.length : 0);
  
  await browser.close();
  await chrome.kill();
})();
