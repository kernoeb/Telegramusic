import puppeteer from 'puppeteer';

const DEEZER_EMAIL = process.env.DEEZER_EMAIL;
const DEEZER_PASSWORD = process.env.DEEZER_PASSWORD;

if (!DEEZER_EMAIL || !DEEZER_PASSWORD) {
  throw new Error('Missing environment variables');
}

const browser = await puppeteer.launch({ headless: false }); // Set to true if you don't need UI
const page = await browser.newPage();

await page.goto('https://www.deezer.com/login');

// Try to accept cookies #gdpr-btn-accept-all
try {
  await page.waitForSelector('#gdpr-btn-accept-all', { timeout: 5000 }); // maybe this is not Europe lol
  await page.click('#gdpr-btn-accept-all');
} catch (error) {
  console.error('Failed to accept cookies:', error);
}

// Wait for the login form
await page.waitForSelector('input[name="email"]');

// Fill in credentials
await page.type('input[name="email"]', DEEZER_EMAIL, { delay: 10 });
await page.type('input[name="password"]', DEEZER_PASSWORD, { delay: 10 });

// Click login button
await page.click('button[type="submit"]');

// Wait for navigation
await page.waitForNavigation({ timeout: 0 });

// Get cookies
const cookies = await page.cookies();

// Extract the "arl" cookie
const arlCookie = cookies.find(cookie => cookie.name === 'arl');

if (arlCookie) {
    console.log('ARL Cookie:', arlCookie.value);
} else {
    console.log('ARL Cookie not found!');
}

await browser.close();
