const puppeteer = require('puppeteer-core');
const chromeLauncher = require('chrome-launcher');

(async () => {
  const chrome = await chromeLauncher.launch({ 
    chromeFlags: [
      '--headless',
      '--window-size=1440,900',
      '--enable-webgl',
      '--ignore-gpu-blocklist',
      '--use-gl=angle',
      '--use-angle=metal'
    ] 
  });
  const browser = await puppeteer.connect({ browserURL: `http://localhost:${chrome.port}` });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));

  const detailedState = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    const container = document.querySelector('[data-testid="map-container"]');
    const section = document.querySelector('section[aria-label="Interactive route map"]');
    
    // Check WebGL context error
    let glContextType = null;
    let glVendor = null;
    let glRenderer = null;
    if (canvas) {
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      if (gl) {
        glContextType = gl.constructor.name;
        const dbg = gl.getExtension('WEBGL_debug_renderer_info');
        if (dbg) {
          glVendor = gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL);
          glRenderer = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL);
        }
      }
    }

    return {
      sectionRect: section ? section.getBoundingClientRect() : null,
      containerRect: container ? container.getBoundingClientRect() : null,
      canvasRect: canvas ? canvas.getBoundingClientRect() : null,
      containerComputed: container ? {
        position: window.getComputedStyle(container).position,
        height: window.getComputedStyle(container).height,
        width: window.getComputedStyle(container).width,
        display: window.getComputedStyle(container).display,
        visibility: window.getComputedStyle(container).visibility,
      } : null,
      canvasComputed: canvas ? {
        position: window.getComputedStyle(canvas).position,
        height: window.getComputedStyle(canvas).height,
        width: window.getComputedStyle(canvas).width,
        display: window.getComputedStyle(canvas).display,
        visibility: window.getComputedStyle(canvas).visibility,
        opacity: window.getComputedStyle(canvas).opacity,
      } : null,
      glContextType,
      glVendor,
      glRenderer,
    };
  });

  console.log("Detailed State:", JSON.stringify(detailedState, null, 2));

  await page.screenshot({ path: '/Users/vikaskumar0205/.gemini/antigravity/brain/516e7cb5-8e86-42bd-872b-ace1aed15c97/browser-actual-view.png' });
  console.log("Screenshot saved!");

  await browser.close();
  await chrome.kill();
})();
