const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless'] });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  
  const tree = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="map-container"]');
    if (!el) return "No map-container";
    
    function dump(node, depth = 0) {
      const style = window.getComputedStyle(node);
      let res = "  ".repeat(depth) + node.tagName + "." + node.className + ` [w:${node.offsetWidth}, h:${node.offsetHeight}, op:${style.opacity}, vis:${style.visibility}, disp:${style.display}, z:${style.zIndex}, bg:${style.backgroundColor}]\n`;
      for (const child of node.children) {
        res += dump(child, depth + 1);
      }
      return res;
    }
    return dump(el.parentElement);
  });
  console.log(tree);
  await browser.close();
  await chrome.kill();
})();
