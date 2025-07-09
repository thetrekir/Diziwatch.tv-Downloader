// get_url.js

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

async function getSourceAndSubtitleUrls(episodeUrl) {
    const browser = await puppeteer.launch({ 
        headless: 'new',
        args: [
            '--no-sandbox', 
            '--disable-setuid-sandbox', 
            '--window-size=1920,1080', 
            '--disable-infobars', 
            '--disable-blink-features=AutomationControlled'
        ],
        ignoreDefaultArgs: ['--enable-automation']
    });
    
    const page = await browser.newPage();

    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1920, height: 1080 });
    
    const client = await page.target().createCDPSession();
    await client.send('Network.enable');
    await client.send('Network.setBlockedURLs', { 
        urls: ['*fastly.jsdelivr.net*', '*cdn.jsdelivr.net*'] 
    });

    let foundSource2Url = null;
    let foundSubtitleUrl = null;

    try {
        const detectionPromise = new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                if (foundSource2Url && !foundSubtitleUrl) {
                    resolve();
                } else {
                    reject(new Error("Zaman asimi: URL'ler 20 saniye icinde bulunamadi."));
                }
            }, 20000);

            page.on('request', (request) => {
                const url = request.url();
                let needsCheck = false;

                if (url.includes('source2.php') && !foundSource2Url) {
                    foundSource2Url = url;
                    needsCheck = true;
                }
                
                if (url.includes('translateden.vtt') && !foundSubtitleUrl) {
                    foundSubtitleUrl = url;
                    needsCheck = true;
                }

                if (needsCheck && foundSource2Url && foundSubtitleUrl) {
                    clearTimeout(timeout);
                    resolve();
                }
            });
        });

        page.goto(episodeUrl, { waitUntil: 'networkidle2', timeout: 30000 }).catch(() => {
        });

        await detectionPromise;

        let output = {};
        if (foundSource2Url) output.source_url = foundSource2Url;
        if (foundSubtitleUrl) output.subtitle_url = foundSubtitleUrl;
        
        return output;
        
    } catch (error) {
        if (foundSource2Url) {
            console.warn("Uyarı: Ana kaynak bulundu fakat altyazı bulunamadı.");
            return { source_url: foundSource2Url };
        }

        const errorPath = `error_screenshot_${Date.now()}.png`;
        console.error(`Hata oluştu. Ekran görüntüsü kaydediliyor: ${errorPath}`);
        try {
            await page.screenshot({ path: errorPath, fullPage: true });
        } catch (ssError) {
            console.error(`Ekran görüntüsü alınamadı: ${ssError.message}`);
        }
        
        throw error;

    } finally {
        if (browser) {
            await browser.close();
        }
    }
}

async function main() {
    const args = process.argv.slice(2);
    if (args.length < 1) {
        console.error('Kullanim: node get_media_urls.js "<dizi_bolum_url>"');
        process.exit(1);
    }
    const episodeUrl = args[0];

    try {
        console.log(`URL'ler alınıyor: ${episodeUrl}`);
        const urls = await getSourceAndSubtitleUrls(episodeUrl);

        if (urls && urls.source_url) {
            console.log("\n--- SONUÇ ---");
            console.log(`SOURCE_URL: ${urls.source_url}`);
            if (urls.subtitle_url) {
                console.log(`SUBTITLE_URL: ${urls.subtitle_url}`);
            }
            process.exit(0);
        } else {
            throw new Error("Kaynak URL'si bulunamadi.");
        }
    } catch (e) {
        console.error(`\nHATA: İşlem başarısız oldu.`);
        console.error(`Detay: ${e.message}`);
        process.exit(1);
    }
}

main();
