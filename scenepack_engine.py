"""
AI Scenepack Maker - Çekirdek Orkestrasyon Motoru (Core Orchestration Engine)
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Windows terminali için UTF-8 kodlama uyumu
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from config import ScenepackConfig
from downloader import YouTubeMediaEngine, sanitize_filename, format_timestamp
from scene_detector import SceneDetectorEngine, SceneItem
from face_matcher import FaceMatcherEngine

console = Console()

class ScenepackEngine:
    def __init__(self, config: ScenepackConfig):
        self.config = config
        self.media_engine = YouTubeMediaEngine(config)
        self.scene_engine = SceneDetectorEngine(config)
        self.face_matcher = FaceMatcherEngine(config)

    def register_character(self, name: str, image_paths: List[Path]) -> int:
        """Hedef karakteri ve fotoğraflarını kaydeder."""
        return self.face_matcher.register_character(name, image_paths)

    def process_url(self, url: str, selected_indices: Optional[List[int]] = None) -> List[Path]:
        """
        Verilen video veya playlist URL'sini baştan sona işler:
        1. Video listesini çeker (playlistten seçilenleri filtreler).
        2. Her video için 360p proxy indirir.
        3. Sahne tespiti yapar.
        4. Kare bazlı yapay zeka yüz taraması gerçekleştirir.
        5. Onaylanan sahneleri doğrudan YouTube'dan 1080p kesip kaydeder.
        """
        console.rule("[bold cyan]AI Scenepack Maker Başlatılıyor[/bold cyan]")
        console.print(f"[bold yellow]Hedef URL:[/bold yellow] {url}")
        console.print(f"[bold yellow]Eşleşme Modu:[/bold yellow] [green]{self.config.match_logic.upper()}[/green]")
        console.print(f"[bold yellow]Hedef Karakterler:[/bold yellow] {', '.join(self.face_matcher.characters.keys())}")
        console.print(f"[bold yellow]Minimum Sahne Süresi:[/bold yellow] {self.config.min_scene_duration_sec} sn\n")

        # 1. Metadata çek
        with console.status("[bold green]Video listesi YouTube'dan taranıyor...[/bold green]", spinner="dots"):
            all_videos = self.media_engine.extract_playlist_info(url)

        if selected_indices and len(all_videos) > 1:
            videos = [v for idx, v in enumerate(all_videos, start=1) if idx in selected_indices]
            console.print(f"[bold green]✔ Playlistten seçilen {len(videos)} / {len(all_videos)} video işlenecek.[/bold green]\n")
        else:
            videos = all_videos
            console.print(f"[bold green]✔ Toplam {len(videos)} video bulundu.[/bold green]\n")

        all_exported_files: List[Path] = []
        summary_report: List[Dict[str, Any]] = []

        for v_idx, video_info in enumerate(videos, start=1):
            title = video_info["title"]
            vid_id = video_info["id"]
            vid_url = video_info["url"]
            clean_title = sanitize_filename(title)

            console.rule(f"[bold magenta]Bölüm {v_idx}/{len(videos)}: {title}[/bold magenta]")

            # 2. Hızlı Tarama için 360p Proxy İndir
            console.print(f"[cyan]Adım 1/3:[/cyan] Hızlı analiz için geçici 360p proxy hazırlanıyor...")
            start_t = time.time()
            try:
                proxy_path = self.media_engine.download_proxy_video(vid_url, vid_id)
                console.print(f"  └─ Proxy hazır ({time.time() - start_t:.1f} sn): [dim]{proxy_path.name}[/dim]")
            except Exception as e:
                console.print(f"[bold red]Proxy indirme hatası: {e}[/bold red]")
                continue

            # 3. Sahne Algılama (PySceneDetect)
            console.print(f"[cyan]Adım 2/3:[/cyan] Kamera açıları ve sahne geçişleri saptanıyor...")
            scenes = self.scene_engine.detect_scenes(proxy_path)
            console.print(f"  └─ Toplam [bold yellow]{len(scenes)}[/bold yellow] sahne tespit edildi (>{self.config.min_scene_duration_sec}s).")

            # 4. Yüz Eşleştirme & AI Analizi
            console.print(f"[cyan]Adım 3/3:[/cyan] Yüzler yapay zeka ile taranıyor ({self.config.face_engine})...")
            matched_scenes: List[Dict[str, Any]] = []

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console
            ) as progress:
                task = progress.add_task(f"Sahne Analizi ({title[:25]}...)", total=len(scenes))

                for sc in scenes:
                    match_res = self.face_matcher.match_scene(proxy_path, sc)
                    if match_res["matched"]:
                        matched_scenes.append({
                            "scene": sc,
                            "match_res": match_res
                        })
                    progress.advance(task)

            console.print(f"[bold green]✔ Eşleşen Sahne Sayısı:[/bold green] [bold yellow]{len(matched_scenes)}[/bold yellow] / {len(scenes)}")

            # Eşleşen sahneleri gösteren tablo
            if matched_scenes:
                table = Table(title=f"Tespit Edilen Sahneler ({title})", show_lines=True)
                table.add_column("Sahne #", style="dim", width=8)
                table.add_column("Başlangıç", style="cyan")
                table.add_column("Bitiş", style="cyan")
                table.add_column("Süre", style="green")
                table.add_column("Bulunan Karakter(ler)", style="yellow")
                table.add_column("En İyi Benzerlik (Mesafe)", style="magenta")

                for m in matched_scenes:
                    sc: SceneItem = m["scene"]
                    mres = m["match_res"]
                    chars_str = ", ".join(mres["characters"]) if mres["characters"] else "N/A"
                    best_dists = [f"{c}: {mres['best_distance'][c]:.2f}" for c in mres["characters"]]
                    dist_str = ", ".join(best_dists) if best_dists else "-"

                    table.add_row(
                        str(sc.scene_index),
                        format_timestamp(sc.start_sec),
                        format_timestamp(sc.end_sec),
                        f"{sc.duration_sec:.1f} sn",
                        chars_str,
                        dist_str
                    )
                console.print(table)

                # 5. Yüksek Kalitede Sahne İndirme (Lossless Section Download)
                console.print(f"[bold cyan]▶ Onaylanan {len(matched_scenes)} sahne 1080p yüksek kalitede kesiliyor...[/bold cyan]")
                
                for idx, m in enumerate(matched_scenes, start=1):
                    sc: SceneItem = m["scene"]
                    mres = m["match_res"]
                    chars_tag = "_".join(mres["characters"]) or "Match"

                    # Örn: Scenepack_KurtlarVadisi_B01_Sahne003_Polat_Cakir_01m24s.mp4
                    start_str_short = f"{int(sc.start_sec // 60):02d}m{int(sc.start_sec % 60):02d}s"
                    end_str_short = f"{int(sc.end_sec // 60):02d}m{int(sc.end_sec % 60):02d}s"
                    
                    filename = (
                        f"Scenepack_{clean_title[:30]}_S{sc.scene_index:03d}_{chars_tag}_"
                        f"{start_str_short}-{end_str_short}.mp4"
                    )

                    try:
                        console.print(f"  [{idx}/{len(matched_scenes)}] İndiriliyor: [yellow]{filename}[/yellow]")
                        cut_file = self.media_engine.download_exact_scene_section(
                            video_url=vid_url,
                            start_sec=sc.start_sec,
                            end_sec=sc.end_sec,
                            output_filename=filename
                        )
                        all_exported_files.append(cut_file)
                        console.print(f"  └─ [bold green]Kaydedildi:[/bold green] {cut_file.name}")

                        summary_report.append({
                            "video_title": title,
                            "video_url": vid_url,
                            "scene_index": sc.scene_index,
                            "start_time": format_timestamp(sc.start_sec),
                            "end_time": format_timestamp(sc.end_sec),
                            "duration_sec": sc.duration_sec,
                            "characters": mres["characters"],
                            "file": str(cut_file)
                        })

                    except Exception as e:
                        console.print(f"  └─ [bold red]Kesme hatası ({filename}): {e}[/bold red]")

            else:
                console.print("[dim]Bu videoda aranan karakter eşleşmesi bulunamadı.[/dim]")

            # 6. Temizlik (Geçici Proxy Silme)
            if not self.config.keep_proxy and proxy_path.exists():
                try:
                    os.remove(proxy_path)
                    console.print("[dim]Geçici proxy dosyası temizlendi.[/dim]")
                except Exception:
                    pass

        # 7. JSON Raporu Oluştur (Video kurgu programları için)
        report_path = self.config.output_dir / "scenepack_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary_report, f, ensure_ascii=False, indent=2)

        console.rule("[bold green]İşlem Tamamlandı[/bold green]")
        console.print(f"Toplam Kesilen Sahne: [bold green]{len(all_exported_files)}[/bold green]")
        console.print(f"Çıktı Klasörü: [bold yellow]{self.config.output_dir.resolve()}[/bold yellow]")
        console.print(f"Zaman Damgası Raporu: [bold yellow]{report_path.resolve()}[/bold yellow]\n")

        return all_exported_files
