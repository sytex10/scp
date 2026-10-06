from __future__ import annotations
import sys
import argparse
from pathlib import Path
from typing import List, Dict

# Windows terminallerinde Türkçe cp1254 / cp857 UTF-8 kodlama uyumu
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from config import ScenepackConfig
from scenepack_engine import ScenepackEngine
from downloader import YouTubeMediaEngine
from face_picker import VideoFacePicker

console = Console()

def parse_time_str(time_str: str) -> float:
    """'01:25' veya '85' formatındaki süreyi saniyeye çevirir."""
    parts = time_str.strip().split(":")
    if len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return float(time_str)

def parse_item_selection(input_str: str, total_count: int) -> List[int]:
    """'1', '1,3,5', '1-5' veya 'all' formatını 1-tabanlı indeks listesine dönüştürür."""
    input_str = input_str.strip().lower()
    if input_str in ("all", "tumu", "hepsi", "*", ""):
        return list(range(1, total_count + 1))
    
    indices = set()
    for part in input_str.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start_i = max(1, int(start_s))
                end_i = min(total_count, int(end_s))
                for i in range(start_i, end_i + 1):
                    indices.add(i)
            except ValueError:
                pass
        else:
            try:
                val = int(part)
                if 1 <= val <= total_count:
                    indices.add(val)
            except ValueError:
                pass
    return sorted(list(indices)) if indices else list(range(1, total_count + 1))

def print_banner():
    banner_text = """
 [bold cyan]+======================================================================+[/bold cyan]
 [bold cyan]|[/bold cyan]            [bold yellow]AI YOUTUBE SCENEPACK OLUSTURUCU[/bold yellow]                           [bold cyan]|[/bold cyan]
 [bold cyan]|[/bold cyan]   [white]YouTube Playlist -> PySceneDetect -> DeepFace -> Lossless Cuts[/white]     [bold cyan]|[/bold cyan]
 [bold cyan]+======================================================================+[/bold cyan]
    """
    try:
        console.print(banner_text)
    except Exception:
        print("\n========================================================")
        print("           AI YOUTUBE SCENEPACK OLUSTURUCU")
        print("========================================================\n")

def load_characters_from_dir(chars_dir: Path) -> Dict[str, List[Path]]:
    """
    'characters/' klasöründeki alt klasörleri otomatik okur.
    Örnek:
      characters/
        ├── Polat/ (polat1.jpg, polat2.png)
        └── Cakir/ (cakir1.jpg)
    """
    char_map: Dict[str, List[Path]] = {}
    valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}

    for sub_dir in chars_dir.iterdir():
        if sub_dir.is_dir():
            imgs = [p for p in sub_dir.iterdir() if p.suffix.lower() in valid_extensions]
            if imgs:
                char_map[sub_dir.name] = imgs
        elif sub_dir.is_file() and sub_dir.suffix.lower() in valid_extensions:
            # Tek bir dosya: characters/polat.jpg
            char_map[sub_dir.stem] = [sub_dir]

    return char_map

def main():
    print_banner()

    parser = argparse.ArgumentParser(description="Yapay Zeka ve Yüz Tanıma ile YouTube Scenepack Kesici")
    parser.add_argument("-u", "--url", type=str, help="YouTube Playlist veya Video Linki")
    parser.add_argument("--chars-dir", type=str, help="Karakter fotoğraflarının bulunduğu klasör yolu")
    parser.add_argument("--char1", type=str, help="Karakter 1 İsmi (örn: Polat)")
    parser.add_argument("--char1-img", type=str, nargs="+", help="Karakter 1 Referans Fotoğrafları")
    parser.add_argument("--char2", type=str, help="Karakter 2 İsmi (örn: Cakir)")
    parser.add_argument("--char2-img", type=str, nargs="+", help="Karakter 2 Referans Fotoğrafları")
    parser.add_argument("--logic", choices=["or", "and", "OR", "AND"], default="OR", help="Eşleşme mantığı (OR / AND)")
    parser.add_argument("--min-duration", type=float, default=2.0, help="Minimum sahne süresi (saniye)")
    parser.add_argument("--sample-fps", type=float, default=1.0, help="Saniye başına taranacak kare sayısı (FPS)")
    parser.add_argument("--engine", choices=["deepface", "face_recognition"], default="deepface", help="Yüz tanıma motoru")
    parser.add_argument("--threshold", type=float, default=0.40, help="Yüz benzerlik mesafe eşiği (küçükse daha katı)")
    parser.add_argument("--quality", type=str, default="1080p", help="Çıktı kalitesi (1080p, 720p, best)")
    parser.add_argument("--cookies", type=str, help="YouTube cookies.txt dosya yolu")
    parser.add_argument("--cookies-browser", type=str, help="Tarayıcı çerezleri (chrome, edge, firefox)")
    parser.add_argument("--keep-proxy", action="store_true", help="360p geçici proxy videosunu silme")
    parser.add_argument("--items", type=str, help="Playlistten seçilecek videolar (örn: '1', '1,3', '1-5' veya 'all')")
    parser.add_argument("--pick-gui", action="store_true", help="Videodan görsel pencere açarak karakter yüzü seç")
    parser.add_argument("--pick-at", type=str, help="Videodan belirtilen zaman damgasından yüz al (örn: 02:15 veya 135)")
    parser.add_argument("--pick-name", type=str, default="Polat", help="--pick-at ile seçilen karakterin adı")
    parser.add_argument("-i", "--interactive", action="store_true", help="İnteraktif sihirbaz modunu zorla")

    args = parser.parse_args()

    # Eğer argüman verilmediyse veya -i istendiyse interaktif sihirbazı aç
    is_interactive = args.interactive or (not args.url and not args.chars_dir and not args.char1 and not args.pick_gui and not args.pick_at)

    config = ScenepackConfig()
    config.match_logic = args.logic.upper()
    config.min_scene_duration_sec = args.min_duration
    config.sample_fps = args.sample_fps
    config.face_engine = args.engine
    config.cosine_threshold = args.threshold
    config.keep_proxy = args.keep_proxy
    config.cookies_file = args.cookies
    config.cookies_browser = args.cookies_browser

    if args.quality == "1080p":
        config.final_video_quality = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best"
    elif args.quality == "720p":
        config.final_video_quality = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best"
    elif args.quality == "best":
        config.final_video_quality = "bestvideo+bestaudio/best"

    characters_dict: Dict[str, List[Path]] = {}
    media_engine = YouTubeMediaEngine(config)
    face_picker = VideoFacePicker()
    selected_indices: Optional[List[int]] = None

    if is_interactive:
        console.print(Panel("[bold green]İnteraktif Ayar Sihirbazı[/bold green]\nLütfen işlem detaylarını belirtin:", expand=False))
        
        target_url = Prompt.ask("[bold yellow]1. YouTube Playlist veya Video URL'si[/bold yellow]")
        
        # Playlist kontrolü ve video seçimi
        console.print("[cyan]Video/Playlist bilgileri taranıyor...[/cyan]")
        available_videos = media_engine.extract_playlist_info(target_url)
        if len(available_videos) > 1:
            console.print(f"\n[bold yellow]📋 Bu oynatma listesinde {len(available_videos)} video bulundu:[/bold yellow]")
            for v_idx, v in enumerate(available_videos[:12], start=1):
                dur_m = int(v.get("duration", 0) // 60)
                dur_s = int(v.get("duration", 0) % 60)
                console.print(f"  [bold cyan][{v_idx}][/bold cyan] {v['title'][:55]} [dim]({dur_m}:{dur_s:02d})[/dim]")
            if len(available_videos) > 12:
                console.print(f"  [dim]... ve {len(available_videos) - 12} video daha.[/dim]")
            
            console.print("\n[yellow]Hangi bölümler işlensin?[/yellow]")
            console.print("  [white]'all'[/white] = Tümü | [white]'1'[/white] = Sadece 1. video | [white]'1,3,5'[/white] = Belirli videolar | [white]'1-5'[/white] = Aralık")
            items_input = Prompt.ask("Seçiminiz", default="all")
            selected_indices = parse_item_selection(items_input, len(available_videos))
            console.print(f"[green]✔ Toplam {len(selected_indices)} video seçildi.[/green]")

        console.print("\n[cyan]Referans Yüzler Nasıl Belirlensin?[/cyan]")
        console.print("  [1] Bilgisayardan fotoğraf yolu gir (örn: polat.jpg)")
        console.print("  [2] Hazır karakter klasöründen otomatik yükle (./characters/)")
        console.print("  [3] [bold green]DOĞRUDAN VİDEO İÇİNDEN SEÇ[/bold green] (Fotoğraf aramaya gerek yok!)")
        choice = Prompt.ask("Seçiminiz", choices=["1", "2", "3"], default="3")

        if choice == "3":
            console.print("[cyan]Seçim için videonun hızlı proxy görüntüsü hazırlanıyor...[/cyan]")
            first_vid = available_videos[0] if available_videos else {"url": target_url, "id": "preview"}
            proxy_path = media_engine.download_proxy_video(first_vid["url"], first_vid["id"])

            console.print("\n[yellow]Videodan Yüzü Nasıl Seçmek İstersiniz?[/yellow]")
            console.print("  [A] Görsel Oynatıcı Aç (Klavye ile sar, boşlukla dondur, 1-9 ile yüzü seç)")
            console.print("  [B] Zaman Damgası Gir (örn: 02:45 veya 165)")
            sub_choice = Prompt.ask("Yöntem", choices=["A", "B", "a", "b"], default="A").upper()

            if sub_choice == "A":
                characters_dict = face_picker.interactive_gui_picker(proxy_path)
            else:
                while True:
                    cname = Prompt.ask("Karakter Adı", default="Polat")
                    t_str = Prompt.ask(f"{cname} için zaman damgası (örn: 02:15 veya 135 sn)")
                    t_sec = parse_time_str(t_str)
                    saved = face_picker.pick_from_timestamp(proxy_path, t_sec, cname)
                    if saved:
                        characters_dict[cname] = [saved]
                    
                    more = Confirm.ask("Başka bir karakter daha eklemek istiyor musunuz?", default=False)
                    if not more:
                        break

        elif choice == "2":
            folder_path = Prompt.ask("Karakterler klasör yolu", default="characters")
            cdir = Path(folder_path)
            if cdir.exists():
                characters_dict = load_characters_from_dir(cdir)
            else:
                console.print(f"[red]Klasör bulunamadı: {cdir}[/red]")
        
        if not characters_dict and choice == "1":
            # Karakter 1
            c1_name = Prompt.ask("Karakter 1 Adı", default="Polat")
            c1_img = Prompt.ask(f"{c1_name} Referans Fotoğraf Yolu (örn: polat.jpg)")
            characters_dict[c1_name] = [Path(c1_img)]

            # Karakter 2 (Opsiyonel)
            has_c2 = Confirm.ask("İkinci bir karakter eklemek istiyor musunuz?", default=True)
            if has_c2:
                c2_name = Prompt.ask("Karakter 2 Adı", default="Cakir")
                c2_img = Prompt.ask(f"{c2_name} Referans Fotoğraf Yolu (örn: cakir.jpg)")
                characters_dict[c2_name] = [Path(c2_img)]

        # Mantık seçimi
        if len(characters_dict) > 1:
            console.print("\n[yellow]Eşleşme Mantığı:[/yellow]")
            console.print("  [OR]  Karakterlerin herhangi birinin olduğu tüm sahneler")
            console.print("  [AND] Karakterlerin birlikte yer aldığı ikili sahneler")
            logic_choice = Prompt.ask("Seçim", choices=["OR", "AND", "or", "and"], default="OR")
            config.match_logic = logic_choice.upper()

        min_dur = Prompt.ask("Minimum sahne süresi (saniye)", default="2.0")
        config.min_scene_duration_sec = float(min_dur)

    else:
        # CLI Argüman modu
        target_url = args.url
        if not target_url:
            console.print("[bold red]Hata: Bir YouTube URL'si belirtmelisiniz (-u / --url).[/bold red]")
            sys.exit(1)

        # CLI üzerinden doğrudan videodan seçme isteği
        if args.pick_gui or args.pick_at:
            videos = media_engine.extract_playlist_info(target_url)
            if not videos:
                console.print("[bold red]Video bilgisi alınamadı.[/bold red]")
                sys.exit(1)
            first_vid = videos[0]
            proxy_path = media_engine.download_proxy_video(first_vid["url"], first_vid["id"])

            if args.pick_gui:
                characters_dict = face_picker.interactive_gui_picker(proxy_path)
            elif args.pick_at:
                t_sec = parse_time_str(args.pick_at)
                saved = face_picker.pick_from_timestamp(proxy_path, t_sec, args.pick_name)
                if saved:
                    characters_dict[args.pick_name] = [saved]

        if args.chars_dir:
            cdir = Path(args.chars_dir)
            if cdir.exists():
                characters_dict.update(load_characters_from_dir(cdir))
            else:
                console.print(f"[bold red]Karakter klasörü bulunamadı: {cdir}[/bold red]")
                sys.exit(1)

        if args.char1 and args.char1_img:
            characters_dict[args.char1] = [Path(p) for p in args.char1_img]

        if args.char2 and args.char2_img:
            characters_dict[args.char2] = [Path(p) for p in args.char2_img]

        if args.items:
            all_vids = media_engine.extract_playlist_info(target_url)
            selected_indices = parse_item_selection(args.items, len(all_vids))

    if not characters_dict:
        console.print("[bold red]Hata: En az bir karakter ve referans fotoğraf tanımlamalısınız![/bold red]")
        sys.exit(1)

    # Motoru başlat ve çalıştır
    engine = ScenepackEngine(config)

    for char_name, img_paths in characters_dict.items():
        engine.register_character(char_name, img_paths)

    engine.process_url(target_url, selected_indices)

if __name__ == "__main__":
    main()
