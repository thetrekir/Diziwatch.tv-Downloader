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
    
    print_lock = threading.Lock()

    def download_segments(playlist_url, output_path, referer, description, apply_rate_limit: bool, lock: threading.Lock, pbar: tqdm):
        scraper = cloudscraper.create_scraper()
        
        try:
            playlist_response = scraper.get(playlist_url, headers={'Referer': referer}, timeout=20)
            playlist_response.raise_for_status()
            playlist_text = playlist_response.text
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"{description} için playlist alınamadı: {e}")

        segment_urls = re.findall(r'^(https?://.+)', playlist_text, re.MULTILINE)
        if not segment_urls: raise ValueError(f"{description} için segment URL'leri bulunamadı.")
        
        with open(output_path, 'wb') as f_out:
            segments_in_burst = 0
            burst_limit = random.randint(40, 60)
            
            for i, url in enumerate(segment_urls):
                retries = 0
                max_retries_per_segment = 5
                while retries < max_retries_per_segment:
                    try:
                        segment_response = scraper.get(url, headers={'Referer': referer}, timeout=25)
                        segment_response.raise_for_status()
                        f_out.write(segment_response.content)
                        with lock: pbar.update(1)
                        break 
                    except requests.exceptions.RequestException as e:
                        retries += 1
                        error_str = str(e)
                        
                        if 'RemoteDisconnected' in error_str: error_msg, wait_time = "Sunucu bağlantıyı kapattı", 8
                        else: error_msg, wait_time = "Bağlantı hatası", 5 * retries
                        
                        if retries >= max_retries_per_segment:
                            with lock: pbar.close()
                            raise RuntimeError(f"{description} Segment {i+1} indirilemedi. Hata: {error_msg}")
                        
                        final_wait = min(wait_time, 30)
                        with lock: pbar.set_postfix_str(f"Hata! {final_wait}s sonra tekrar...")
                        time.sleep(final_wait)
                        with lock: pbar.set_postfix_str("")

                if apply_rate_limit and not ignore_rate_limit:
                    segments_in_burst += 1
                    if segments_in_burst >= burst_limit and (i + 1) < len(segment_urls):
                        pause_duration = random.uniform(2, 5)
                        with lock: pbar.set_postfix_str(f"Rate-Limit mola ({int(pause_duration)}s)")
                        time.sleep(pause_duration)
                        with lock: pbar.set_postfix_str("")
                        segments_in_burst = 0
                        burst_limit = random.randint(40, 60)

    def animate_spinner(pbar: tqdm, lock: threading.Lock, stop_event: threading.Event):
        spinner_chars = ['|', '/', '-', '\\']
        idx = 0
        while not stop_event.is_set():
            with lock:
                pbar.set_description_str(f"   [-> İndiriliyor] {spinner_chars[idx % len(spinner_chars)]}")
                pbar.refresh()
            idx += 1
            time.sleep(0.1) # Sabit animasyon hızı

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
        
        available_streams = []
        stream_matches = re.finditer(r'#EXT-X-STREAM-INF:(?P<attributes>.*?)\n(?P<url>https?://[^\s]+)', master_playlist_content)
        
        for match in stream_matches:
            attrs = match.group('attributes')
            url = match.group('url')
            res_match = re.search(r'RESOLUTION=\d+x(\d+)', attrs)
            resolution = int(res_match.group(1)) if res_match else 0
            bw_match = re.search(r'BANDWIDTH=(\d+)', attrs)
            bandwidth = int(bw_match.group(1)) if bw_match else 0
            available_streams.append({'url': url, 'resolution': resolution, 'bandwidth': bandwidth})

        if not available_streams:
            raise ValueError("Kalite seçenekleri bulunamadı.")
            
        available_streams.sort(key=lambda x: (x['resolution'], x['bandwidth']), reverse=True)
        best_stream_url = available_streams[0]['url']
        best_resolution = available_streams[0]['resolution']
        print(f"-> {best_resolution}p kalitesi indirilmek üzere seçildi.")

        audio_uri_match = re.search(r'#EXT-X-MEDIA:TYPE=AUDIO.*?URI="(.*?)"', master_playlist_content)
        pbar_format = "{desc} {percentage:3.0f}% {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]"

        if audio_uri_match:
            print("-> Ayrı akışlar tespit edildi. Paralel indirme başlıyor...")
            audio_playlist_url = urljoin(m_php_url, audio_uri_match.group(1))
            video_playlist_url = best_stream_url
            
            video_playlist_text = scraper.get(video_playlist_url, headers=headers_player).text
            audio_playlist_text = scraper.get(audio_playlist_url, headers=headers_player).text
            total_video_segments = len(re.findall(r'^(https?://.+)', video_playlist_text, re.MULTILINE))
            total_audio_segments = len(re.findall(r'^(https?://.+)', audio_playlist_text, re.MULTILINE))
            total_segments = total_video_segments + total_audio_segments

            with tqdm(total=total_segments, unit=" parça", dynamic_ncols=True, bar_format=pbar_format) as pbar:
                stop_spinner = threading.Event()
                
                spinner_thread = threading.Thread(target=animate_spinner, args=(pbar, print_lock, stop_spinner))
                video_task = threading.Thread(target=download_segments, args=(video_playlist_url, temp_video_path, m_php_url, "Video", True, print_lock, pbar))
                audio_task = threading.Thread(target=download_segments, args=(audio_playlist_url, temp_audio_path, m_php_url, "Ses", False, print_lock, pbar))
                
                spinner_thread.start()
                video_task.start()
                audio_task.start()

                video_task.join()
                audio_task.join()
                stop_spinner.set()
                spinner_thread.join()

            print("-> İndirmeler tamamlandı.")
            print("-> FFmpeg ile birleştirme işlemi hazırlanıyor...")
            command = ['ffmpeg', '-y', '-i', temp_video_path, '-i', temp_audio_path, '-async', '1']
            if altyazi_var: command.extend(['-i', temp_subtitle_path])
            command.extend(['-map', '0:v:0', '-map', '1:a:0'])
            if altyazi_var:
                command.extend(['-map', '2:s:0', '-c:s', 'mov_text', '-metadata:s:s:0', 'language=tur'])
            command.extend(['-c:v', 'copy', '-c:a', 'copy', final_output_path])
        else:
            print("-> Birleşik video/ses akışı tespit edildi.")
            combined_playlist_url = best_stream_url
            
            combined_playlist_text = scraper.get(combined_playlist_url, headers=headers_player).text
            total_segments = len(re.findall(r'^(https?://.+)', combined_playlist_text, re.MULTILINE))

            with tqdm(total=total_segments, unit=" parça", dynamic_ncols=True, bar_format=pbar_format) as pbar:
                stop_spinner = threading.Event()
                spinner_thread = threading.Thread(target=animate_spinner, args=(pbar, print_lock, stop_spinner))
                
                spinner_thread.start()
                download_segments(combined_playlist_url, temp_video_path, m_php_url, "Video/Ses", True, print_lock, pbar)
                stop_spinner.set()
                spinner_thread.join()

            print("-> İndirmeler tamamlandı.")
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
