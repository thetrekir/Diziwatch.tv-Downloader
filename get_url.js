// get_url.js

const puppeteer = require('puppeteer');

async function getSourceAndSubtitleUrls(episodeUrl) {
    const browser = await puppeteer.launch({ 
        headless: true,
        args: [
            '--window-size=1920,1080', 
            '--log-level=3',
            '--disable-blink-features=AutomationControlled'
        ],
        ignoreDefaultArgs: ['--enable-automation']
    });
    
    const page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080 });
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36');

    let foundSource2Url = null;
    let foundSubtitleUrl = null;

    try {
        const urlsPromise = new Promise((resolve, reject) => {
            page.on('request', (request) => {
                const url = request.url();
                
                if (url.includes('source2.php')) {
                    foundSource2Url = url;
                }
                
                if (url.includes('translateden.vtt')) {
                    foundSubtitleUrl = url;
                }

                if (foundSource2Url && foundSubtitleUrl) {
                    resolve();
                }
            });

            setTimeout(() => {
                if (foundSource2Url) {
                    resolve();
                } else {
                    reject(new Error("Zaman asimi: Ana kaynak (source2.php) 30 saniye icinde bulunamadi."));
                }
            }, 30000);
        });

        const client = await page.target().createCDPSession();
        await client.send('Network.setBlockedURLs', { urls: ['*fastly.jsdelivr.net*'] });
        await client.send('Debugger.setBreakpointsActive', { active: false });

        await page.goto(episodeUrl, { waitUntil: 'networkidle2' });
        
        await urlsPromise;

        let output = {};
        if (foundSource2Url) output.source_url = foundSource2Url;
        if (foundSubtitleUrl) output.subtitle_url = foundSubtitleUrl;
        return output;
        
    } finally {
        await browser.close();
    }
}

async function main() {
    const args = process.argv.slice(2);
    if (args.length < 1) {
        console.error('Kullanim: node get_url.js "<dizi_bolum_url>"');
        process.exit(1);
    }
    const episodeUrl = args[0];

    try {
        const urls = await getSourceAndSubtitleUrls(episodeUrl);
        if (urls.source_url) {
            console.log(`SOURCE_URL: ${urls.source_url}`);
            if (urls.subtitle_url) {
                console.log(`SUBTITLE_URL: ${urls.subtitle_url}`);
            }
            process.exit(0);
        } else {
            throw new Error("Ana kaynak URL'si (source2.php) bulunamadi.");
        }
    } catch (e) {
        console.error(`HATA: Radar çalışırken hata oluştu.`);
        console.error(`Detay: ${e.message}`);
        process.exit(1);
    }
}

main();
