import sys
import re
import os
import json
import subprocess
from urllib.parse import urlparse, urljoin
import random
import threading
import time
import requests
import cloudscraper
from bs4 import BeautifulSoup
from tqdm import tqdm

# --- MOTOR PARÇALARI ---

#Sitedeki korumalar:

#Soğan Zarı #1: Fastly.jsdelivr.net İle Ana Sayfa Geri Atması
# fastly.jsdelivr.net scripti ile otomasyonu ve F12 yi anında tespit edip dışarı atar.

#Soğan Zarı #2: JavaScript Obfuscation
# Playerın tüm JS kodunu, değişken adlarını anlamsız harflere, mantığı da karmaşık bloklara çevirerek tersine mühendisliği "engeller".

#Soğan Zarı #3: Iframe 'debugger;' Tuzağı
# Player iframeinin içine gömülü 'debugger;' komutları ile F12 yi anında tespit edip playeri dondurur.

#Soğan Zarı #4: Headless Tarayıcı Tespiti
# En orospu çocuğu olan katman. Headless modda çalışan tarayıcıyı tespit edip ölü taklidi yapar ve kritik 'source2.php' isteğini hiç göndermez.

#Soğan Zarı #5: Referer ve Cloudflare
# Her bir yönlendirme adımında doğru 'Referer' başlığını kontrol eder ek olarak Cloudflare ile bot tespiti yapar.

#Soğan Zarı #6: Sahte '.jpg' Segmentleri
# Videoyu '.ts' yerine '.jpg' uzantılı sahte resim dosyaları olarak sunarak standart indirme araçlarını kandırır.

#Soğan Zarı #7: Dinamik URL
# source2.php -> m.php -> l.php ve/veya ld.php -> segmentler. Her adım, bir öncekinden gelen anahtarla açılır, zinciri takip etmeyen yolda kalır.

NODE_SCRIPT_PATH = 'get_url.js'

def sanitize_filename(name: str) -> str:
    cleaned_name = ' '.join(name.split())
    return re.sub(r'[\\/*?:"<>|]', "", cleaned_name).strip()

def parse_url_for_info(episode_url: str) -> dict:
    try:
        path_parts = urlparse(episode_url).path.strip('/').split('/')
        dizi_slug, sezon_slug, bolum_slug = path_parts[1], path_parts[2], path_parts[3]
        dizi_adi = dizi_slug.replace('-', ' ').title()
        sezon_adi = sezon_slug.replace('-', ' ').capitalize()
        match = re.match(r'bolum-(\d+)', bolum_slug, re.IGNORECASE)
        bolum_no = int(match.group(1)) if match else None
        bolum_adi = f"{match.group(1)}. Bölüm" if match else bolum_slug.replace('-', ' ').capitalize()
        folder_name = sanitize_filename(f"{dizi_adi} {sezon_adi}")
        file_name = sanitize_filename(f"{bolum_adi}.mp4")
        output_path = os.path.join(folder_name, file_name)
        return {"output_path": output_path, "display_name": f"{dizi_adi} - {sezon_adi} - {bolum_adi}", "dizi_adi": dizi_adi, "bolum_no": bolum_no}
    except Exception:
        slug = urlparse(episode_url).path.strip('/').split('/')[-1]
        filename = f"{slug or 'video'}.mp4"
        return {"output_path": filename, "display_name": filename, "dizi_adi": None, "bolum_no": None}

def radari_calistir(episode_url: str, get_fillers: bool = False, show_name: str = None) -> dict:
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            command = ['node', NODE_SCRIPT_PATH, episode_url]
            if get_fillers and show_name:
                command.extend(['--get-fillers', show_name])
            
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )

            if process.stderr:
                for line in process.stderr.strip().splitlines():
                    print(f"   [Node.js]: {line}")

            results = {'source_url': None, 'subtitle_url': None, 'filler_list': None}
            for line in process.stdout.strip().splitlines():
                if line.startswith('SOURCE_URL:'):
                    results['source_url'] = line.split(':', 1)[1].strip()
                elif line.startswith('SUBTITLE_URL:'):
                    results['subtitle_url'] = line.split(':', 1)[1].strip()
                elif line.startswith('FILLER_LIST:'):
                    try:
                        filler_data = line.split(':', 1)[1].strip()
                        results['filler_list'] = json.loads(filler_data)
                    except json.JSONDecodeError:
                        print("   - UYARI: Node.js'ten gelen filler listesi parse edilemedi.")

            if not results['source_url']:
                raise ValueError("Radardan sinyal alındı ama source2.php URL'si boş geldi.")
            
            if attempt > 1:
                print(f"   - Radar {attempt}. denemede başarılı oldu.")

            return results

        except Exception as e:
            print(f"   - UYARI: Radar denemesi [{attempt}/{max_attempts}] başarısız oldu: {e}")
            if attempt == max_attempts:
                print("   - HATA: Tüm radar denemeleri başarısız oldu. Bu bölüm geçiliyor.")
                raise e
            else:
                time.sleep(3)

def indir_ve_donustur(source_url: str, subtitle_url: str, final_output_path: str, ignore_rate_limit: bool = False):
    
    temp_video_path = final_output_path + ".video.ts"
    temp_audio_path = final_output_path + ".audio.aac"
    temp_subtitle_path = final_output_path + ".vtt"
    temp_files = [temp_video_path, temp_audio_path, temp_subtitle_path]
    
    def download_segments(playlist_url, output_path, referer, description):
        scraper = cloudscraper.create_scraper()
        playlist_response = scraper.get(playlist_url, headers={'Referer': referer})
        playlist_response.raise_for_status()
        segment_urls = re.findall(r'^(https://.+)', playlist_response.text, re.MULTILINE)
        if not segment_urls: raise ValueError(f"{description} için segment URL'leri bulunamadı.")
        
        with open(output_path, 'wb') as f_out:
            pbar = tqdm(total=len(segment_urls), desc=f"   [-> {description}]", unit=" parça", leave=True)
            
            segments_in_burst = 0
            burst_limit = random.randint(20, 30) 

            for i, url in enumerate(segment_urls):
                try:
                    segment_response = scraper.get(url, headers={'Referer': referer}, timeout=20)
                    segment_response.raise_for_status()
                    f_out.write(segment_response.content)
                    
                    pbar.update(1)
                    
                    if not ignore_rate_limit:
                        segments_in_burst += 1
                        if segments_in_burst >= burst_limit and (i + 1) < len(segment_urls):
                            pause_duration = random.uniform(2, 4)
                            pbar.set_postfix_str(f"Rate-Limit önleme için ({int(pause_duration)}s mola)...")
                            time.sleep(pause_duration)
                            pbar.set_postfix_str("") 
                            segments_in_burst = 0
                            burst_limit = random.randint(20, 30)
                
                except requests.exceptions.RequestException as e:
                    pbar.set_postfix_str("Bağlantı hatası, 5sn sonra tekrar deneniyor...")
                    time.sleep(5)
                    continue

    try:
        scraper = cloudscraper.create_scraper()
        headers_main = {'Referer': "https://diziwatch.tv/"}
        source_response = scraper.get(source_url, headers=headers_main)
        m_php_url = source_response.json()['playlist'][0]['sources'][0]['file']
        headers_player = {'Referer': source_url}
        master_playlist_response = scraper.get(m_php_url, headers=headers_player)
        master_playlist_content = master_playlist_response.text

        altyazi_var = False
        if subtitle_url:
            try:
                print("-> Altyazı dosyası indiriliyor...")
                sub_response = scraper.get(subtitle_url, headers={'Referer': m_php_url})
                sub_response.raise_for_status()
                with open(temp_subtitle_path, 'wb') as f: f.write(sub_response.content)
                altyazi_var = os.path.exists(temp_subtitle_path) and os.path.getsize(temp_subtitle_path) > 0
            except Exception as e:
                print(f"UYARI: Altyazı indirilemedi. Sebep: {e}. İşleme altyazısız devam edilecek.")
                altyazi_var = False

        audio_uri_match = re.search(r'#EXT-X-MEDIA:TYPE=AUDIO.*?URI="(.*?)"', master_playlist_content)
        
        if audio_uri_match:
            print("-> Ayrı akışlar tespit edildi. Paralel indirme başlıyor...")
            audio_playlist_url = urljoin(m_php_url, audio_uri_match.group(1))
            video_playlist_match = re.findall(r'#EXT-X-STREAM-INF:.*\n(https.*)', master_playlist_content)
            video_playlist_url = video_playlist_match[-1]
            video_task = threading.Thread(target=download_segments, args=(video_playlist_url, temp_video_path, m_php_url, "Video"))
            audio_task = threading.Thread(target=download_segments, args=(audio_playlist_url, temp_audio_path, m_php_url, "Ses"))
            video_task.start()
            audio_task.start()
            video_task.join()
            audio_task.join()
            print("-> İndirmeler tamamlandı.")
            print("-> FFmpeg ile birleştirme işlemi hazırlanıyor...")
            command = ['ffmpeg', '-y', '-i', temp_video_path, '-i', temp_audio_path]
            if altyazi_var: command.extend(['-i', temp_subtitle_path])
            command.extend(['-map', '0:v:0', '-map', '1:a:0'])
            if altyazi_var:
                command.extend(['-map', '2:s:0', '-c:s', 'mov_text', '-metadata:s:s:0', 'language=tur'])
            command.extend(['-c:v', 'copy', '-c:a', 'copy', final_output_path])
        else:
            print("-> Birleşik video/ses akışı tespit edildi.")
            playlist_url_match = re.search(r'^(https://.+)', master_playlist_content, re.MULTILINE)
            if not playlist_url_match: raise ValueError("Birleşik akış için playlist URL'si bulunamadı.")
            combined_playlist_url = playlist_url_match.group(1)
            download_segments(combined_playlist_url, temp_video_path, m_php_url, "Video/Ses")
            print("-> FFmpeg ile dönüştürme işlemi hazırlanıyor (remux)...")
            command = ['ffmpeg', '-y', '-i', temp_video_path]
            if altyazi_var: command.extend(['-i', temp_subtitle_path])
            command.extend(['-c', 'copy'])
            if altyazi_var:
                command.extend(['-map', '0', '-map', '-0:s', '-map', '1', '-c:s', 'mov_text', '-metadata:s:s:0', 'language=tur'])
            command.extend(['-bsf:a', 'aac_adtstoasc', final_output_path])

        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("-> Dönüştürme tamamlandı.")

    except FileNotFoundError:
        raise RuntimeError("FFmpeg bulunamadı. Kurup PATH'e eklediğinden emin ol.")
    except subprocess.CalledProcessError as e:
        print(f"HATA: FFmpeg dönüştürme sırasında hata verdi.")
        raise
    finally:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

def indir_diziwatch(episode_url, output_path, ignore_rate_limit: bool = False):
    print("-> Sistem (Diziwatch/Node.js/FFmpeg) deneniyor...")
    urls = radari_calistir(episode_url)
    print("   - Sinyal yakalandı. İşleme başlıyor.")
    if urls.get('subtitle_url'):
        print("   - Altyazı sinyali de yakalandı.")
    indir_ve_donustur(urls['source_url'], urls.get('subtitle_url'), output_path, ignore_rate_limit)
    print("-> Başarılı.")
    return True

# --- KONTROL ---
def main():
    if len(sys.argv) < 2:
        print("Kullanım:\n  Tek bölüm: python ...py \"<bölüm_linki>\" [--ignore-rate-limit]\n  Tüm sezon: python ...py \"<herhangi_bir_sezon_linki>\" --sezon [--only-canon] [--ignore-rate-limit]")
        return

    start_url = sys.argv[1]
    season_mode = '--sezon' in sys.argv
    only_canon_mode = '--only-canon' in sys.argv
    ignore_rate_limit = '--ignore-rate-limit' in sys.argv
    
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'})
    
    successful_downloads, failed_downloads = [], []
    episode_links = []
    filler_list = None
    first_episode_data = None 

    print("Analiz başlıyor...")
    if season_mode:
        print("Sezon modu aktif. Bölüm listesi alınıyor...")
        try:
            response = session.get(start_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            # --- HARDCODED ---
            sezon_liste_selector = "#router-view > div.mt-5.sm\:my-5.sm\:px-4 > div > div.sm\:col-span-3.w-full > div.flex.flex-col.mt-2.overflow-auto"
            container = soup.select_one(sezon_liste_selector)
            if not container: raise ValueError(f"Sezonun bölüm listesi konteyneri bulunamadı.")
            links_found = container.select('a')
            if not links_found: raise ValueError("Bölüm listesi konteyneri içinde link ('a' etiketi) bulunamadı.")
            for a_tag in links_found:
                episode_links.append(urljoin(start_url, a_tag['href']))
        except Exception as e:
            print(f"HATA: Sezon analizi başarısız oldu. Sebep: {e}"); return
    else:
        print("Tek bölüm modu aktif.")
        episode_links.append(start_url)
    
    if not episode_links:
        print("HATA: İşlenecek bölüm bulunamadı."); return

    if season_mode and only_canon_mode:
        print("-> --only-canon modu aktif. Filler listesi alınıyor...")
        
        first_ep_info = parse_url_for_info(episode_links[0])
        dizi_adi = first_ep_info.get('dizi_adi')
        
        if dizi_adi:
            base_url_parts = urlparse(episode_links[0]).path.strip('/').split('/')
            if len(base_url_parts) >= 3:
                sezon_url_parcasi = "/".join(base_url_parts[:3])
                # Bunu yapmassak 1. bölüm ve filler için ayrı tarayıcı açarız, verimsiz.
                first_episode_url_to_scan = urljoin(start_url, f"/{sezon_url_parcasi}/bolum-1")
                print("-> Tarama için URL hedeflendi")

                try:
                    print("-> Tarama başladı...")
                    first_episode_data = radari_calistir(first_episode_url_to_scan, get_fillers=True, show_name=dizi_adi)
                    filler_list = first_episode_data.get('filler_list')
                    
                    if filler_list is not None:
                        if not filler_list:
                            print("-> Filler listesi boş geldi. Muhtemelen bu animede filler bölüm yok.")
                        
                        total_episodes = len(episode_links)
                        episode_numbers = [
                            info.get('bolum_no') for link in episode_links 
                            if (info := parse_url_for_info(link)) and info.get('bolum_no')
                        ]
                        canon_count = len([ep_num for ep_num in episode_numbers if ep_num not in filler_list])
                        
                        print(f"-> Özet: Toplam {total_episodes} bölümden, {len(filler_list)} tanesi filler/mixed olarak işaretlendi.")
                        print(f"-> İndirilecek canon bölüm sayısı: {canon_count}")
                    else:
                        print("UYARI: Filler listesi alınamadı. Tüm bölümler indirilecek.")
                except Exception as e:
                    print(f"UYARI: Filler listesi ve 1. bölüm verisi alınırken hata oluştu: {e}. Normal işleme devam edilecek.")
                    first_episode_data = None
            else:
                 print("UYARI: URL yapısı beklenenden farklı, 1. bölüm linki oluşturulamadı.")
        else:
            print("UYARI: Dizi adı URL'den parse edilemedi, filler listesi alınamıyor.")

    print(f"Toplam {len(episode_links)} bölüm işlenecek.")
    if ignore_rate_limit: print("UYARI: Rate-limit önlemleri devre dışı bırakıldı.")
    print("=" * 40)

    for i, link in enumerate(episode_links, 1):
        info = parse_url_for_info(link)
        output_path = info['output_path']
        display_name = info['display_name']
        bolum_no = info.get('bolum_no')
        
        print(f"İşlem [{i}/{len(episode_links)}]: {display_name}")
        
        if only_canon_mode and filler_list is not None and bolum_no in filler_list:
            print("-> FILLER, geçildi.")
            successful_downloads.append(f"{display_name} (Filler - Atlandı)")
            print("-" * 40)
            continue

        try:
            folder = os.path.dirname(output_path)
            if folder: os.makedirs(folder, exist_ok=True)
            if os.path.exists(output_path):
                print("-> MEVCUT, geçildi.")
                successful_downloads.append(f"{display_name} (Mevcut)")
                continue
            
            if bolum_no == 1 and first_episode_data and first_episode_data.get('source_url'):
                print("-> Önceden alınan 1. bölüm verileri kullanılıyor...")
                urls = first_episode_data
            else:
                print("-> Sistem (Diziwatch/Node.js/FFmpeg) deneniyor...")
                urls = radari_calistir(link)
            
            if not urls or not urls.get('source_url'):
                raise ValueError("Bölüm için kaynak URL'si alınamadı.")

            print("   - Sinyal yakalandı. İşleme başlıyor.")
            if urls.get('subtitle_url'):
                print("   - Altyazı sinyali de yakalandı.")
            
            indir_ve_donustur(urls['source_url'], urls.get('subtitle_url'), output_path, ignore_rate_limit)
            print("-> Başarılı.")
            successful_downloads.append(display_name)
            
        except Exception as e:
            error_info = f"'{display_name}' - Sebep: {e}"
            print(f"HATA: {error_info}")
            failed_downloads.append(error_info)
        finally:
           # if i < len(episode_links):
           #    wait_time = random.uniform(3, 7)
           #     if not ignore_rate_limit:
           #         print(f"-> Sonraki bölüme geçmeden önce {int(wait_time)} saniye bekleniyor...")
           #         time.sleep(wait_time)
            print("-" * 40)

    print("\nİşlem Raporu:")
    print("=" * 40)
    if successful_downloads: print(f"Başarılı/Atlanan: {len(successful_downloads)}")
    if failed_downloads: 
        print(f"Başarısız: {len(failed_downloads)}")
        for item in failed_downloads:
            print(f"  - {item}")
    print("=" * 40)
    print("Operasyon tamamlandı.")

if __name__ == '__main__':
    main()
