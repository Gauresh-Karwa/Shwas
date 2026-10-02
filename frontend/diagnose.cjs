const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  const logs = [];
  page.on('console', msg => {
    logs.push(`[${msg.type()}] ${msg.text()}`);
  });
  
  page.on('pageerror', err => {
    logs.push(`[PAGE ERROR] ${err.message}`);
  });
  
  try {
    await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(10000);
  } catch (e) {
    logs.push(`[NAV ERROR] ${e.message}`);
  }
  
  console.log('\n=== ALL CONSOLE LOGS ===');
  logs.forEach(l => console.log(l));
  
  await browser.close();
})();