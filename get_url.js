// get_url.js

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs').promises;
const cheerio = require('cheerio');

puppeteer.use(StealthPlugin());

const CACHE_FILE = 'fillerlist_cache.json';
const CACHE_DURATION_DAYS = 7;

function normalizeShowName(name) {
    if (!name) return '';
    return name
        .toLowerCase()
        .replace(/\b(part|season|saison|sezon)\s*\d+/g, '')
        .replace(/one-piece-1/g, 'one piece')
        .replace(/[^\w\s]/g, ' ')
        .replace(/(.)\1+/g, '$1')
        .replace(/\s+/g, ' ')
        .trim();
}

async function getDiziwatchData(page, episodeUrl) {
    let foundSource2Url = null;
    let foundSubtitleUrl = null;

    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1920, height: 1080 });
    
    const client = await page.target().createCDPSession();
    await client.send('Network.enable');
    await client.send('Network.setBlockedURLs', { 
        urls: ['*fastly.jsdelivr.net*', '*cdn.jsdelivr.net*'] 
    });

    let subtitlePriority = 0;
    let resolveDetection;
    const detectionPromise = new Promise(resolve => { resolveDetection = resolve; });

    const requestListener = (request) => {
        const url = request.url();
        if (url.includes('source2.php') && !foundSource2Url) {
            foundSource2Url = url;
        }
        if (url.includes('.vtt')) {
           let p = 0;
           if (url.includes('translateden.vtt')) p = 4;
           else if (url.includes('.tr.')) p = 3;
           else if (!url.includes('en.vtt')) p = 2;
           else if (url.includes('en.vtt')) p = 1;
           if (p > subtitlePriority) {
               foundSubtitleUrl = url;
               subtitlePriority = p;
           }
        }
        if (foundSource2Url && subtitlePriority === 4) {
            resolveDetection();
        }
    };
    
    page.on('request', requestListener);
    detectionPromise.finally(() => page.off('request', requestListener));

    const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error("Zaman asimi: URL'ler 20 saniye icinde bulunamadi.")), 20000)
    );

    await page.goto(episodeUrl, { waitUntil: 'networkidle2', timeout: 30000 }).catch(() => {});

    if (!foundSource2Url) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        if (!foundSource2Url) {
            try {
                await page.mouse.click(page.viewport().width / 2, page.viewport().height / 2);
            } catch (e) {}
        }
    }
    
    try {
        await Promise.race([detectionPromise, timeoutPromise]);
    } catch (e) {
        if (!foundSource2Url) {
            throw e;
        }
    }

    return { source_url: foundSource2Url, subtitle_url: foundSubtitleUrl };
}

async function getFillerList(page, showNameToSearch) {
    let allShows = {}, cacheIsValid = false;
    try {
        const stats = await fs.stat(CACHE_FILE);
        const ageInDays = (new Date().getTime() - stats.mtime.getTime()) / (1000 * 3600 * 24);
        if (ageInDays < CACHE_DURATION_DAYS) cacheIsValid = true;
    } catch (e) { cacheIsValid = false; }

    if (cacheIsValid) {
        allShows = JSON.parse(await fs.readFile(CACHE_FILE, 'utf-8'));
    } else {
        await page.goto("https://www.animefillerlist.com/shows/", { waitUntil: 'networkidle2' });
        const content = await page.content();
        const $ = cheerio.load(content);
        $('#ShowList a').each((i, el) => { allShows[$(el).text().trim()] = $(el).attr('href'); });
        await fs.writeFile(CACHE_FILE, JSON.stringify(allShows, null, 2));
    }

    const normalizedSearch = normalizeShowName(showNameToSearch);
    let foundLink = null;
    for (const [name, link] of Object.entries(allShows)) {
        if (normalizeShowName(name) === normalizedSearch) {
            foundLink = link;
            break;
        }
    }

    if (!foundLink) return [];
    
    await page.goto("https://www.animefillerlist.com" + foundLink, { waitUntil: 'networkidle2' });
    
    try {
        await page.waitForSelector('#Condensed', { timeout: 15000 });
    } catch(e) {
        return [];
    }

    const content = await page.content();
    const $ = cheerio.load(content);
    const fillerEpisodes = new Set();
    // --- HARDCODED ---
    const episodeLinks = $('div.filler span.Episodes a');
    
    episodeLinks.each((j, el) => {
        const text = $(el).text().trim();
        if (text.includes('-')) {
            const [start, end] = text.split('-').map(num => parseInt(num, 10));
            if (!isNaN(start) && !isNaN(end)) for (let k = start; k <= end; k++) fillerEpisodes.add(k);
        } else if (text && !isNaN(text)) {
            fillerEpisodes.add(parseInt(text, 10));
        }
    });

    return Array.from(fillerEpisodes).sort((a, b) => a - b);
}

async function main() {
    const args = process.argv.slice(2);
    if (args.length < 1) {
        process.exit(1);
    }
    const episodeUrl = args[0];
    const getFillersFlagIndex = args.indexOf('--get-fillers');
    const getFillers = getFillersFlagIndex !== -1;
    const showNameToSearch = getFillers ? args[getFillersFlagIndex + 1] : null;

    if (getFillers && !showNameToSearch) {
        process.exit(1);
    }

    const browser = await puppeteer.launch({ 
        headless: 'new',
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1920,1080', '--disable-infobars', '--disable-blink-features=AutomationControlled', '--mute-audio'],
        ignoreDefaultArgs: ['--enable-automation']
    });
    const page = await browser.newPage();
    let finalOutput = {};

    try {
        const diziwatchData = await getDiziwatchData(page, episodeUrl);
        finalOutput.source_url = diziwatchData.source_url;
        finalOutput.subtitle_url = diziwatchData.subtitle_url;

        if (getFillers && showNameToSearch) {
            const fillerList = await getFillerList(page, showNameToSearch);
            finalOutput.filler_list = fillerList;
        }

        if (finalOutput.source_url) console.log(`SOURCE_URL: ${finalOutput.source_url}`);
        if (finalOutput.subtitle_url) console.log(`SUBTITLE_URL: ${finalOutput.subtitle_url}`);
        if (finalOutput.filler_list) console.log(`FILLER_LIST: ${JSON.stringify(finalOutput.filler_list)}`);

    } catch (e) {
        const errorPath = `error_screenshot_${Date.now()}.png`;
        try { await page.screenshot({ path: errorPath, fullPage: true }); } catch (ssError) {}
        process.exit(1);
    } finally {
        if (browser) await browser.close();
    }
}

main();
