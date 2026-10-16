const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));

  const pixelStats = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return null;
    // We can draw the webgl canvas onto a 2d canvas to sample pixels without gl context conflicts!
    const c2d = document.createElement('canvas');
    c2d.width = canvas.width;
    c2d.height = canvas.height;
    const ctx = c2d.getContext('2d');
    ctx.drawImage(canvas, 0, 0);
    const data = ctx.getImageData(0, 0, c2d.width, c2d.height).data;
    
    // Sample 100 pixels
    let nonZero = 0;
    let colors = {};
    for (let i = 0; i < data.length; i += 40) {
      const r = data[i], g = data[i+1], b = data[i+2], a = data[i+3];
      if (a > 0) nonZero++;
      const k = `${r},${g},${b},${a}`;
      colors[k] = (colors[k] || 0) + 1;
    }
    return { nonZero, totalSampled: data.length / 40, colors: Object.entries(colors).slice(0, 5) };
  });

  console.log("Pixel stats from canvas:", pixelStats);
  await browser.close();
  await chrome.kill();
})();
