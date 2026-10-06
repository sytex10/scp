"""
AI Scenepack Maker - Medya İndirme & Bölüm Kesme Motoru (yt-dlp & ffmpeg)
"""

import os
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

from config import ScenepackConfig

def sanitize_filename(name: str) -> str:
    """Dosya adlarındaki geçersiz karakterleri temizler."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip().replace(" ", "_")

def format_timestamp(seconds: float) -> str:
    """Saniyeyi HH:MM:SS.mmm formatına dönüştürür."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:06.3f}"

class YouTubeMediaEngine:
    def __init__(self, config: ScenepackConfig):
        self.config = config
        self.config.temp_dir.mkdir(parents=True, exist_ok=True)
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_base_ydl_opts(self) -> Dict[str, Any]:
        """yt-dlp için temel ve güvenli parametreleri döner."""
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "ignoreerrors": True,
        }
        if self.config.cookies_file and os.path.exists(self.config.cookies_file):
            opts["cookiefile"] = self.config.cookies_file
        elif self.config.cookies_browser:
            opts["cookiesfrombrowser"] = (self.config.cookies_browser, None, None, None)
            
        return opts

    def extract_playlist_info(self, url: str) -> List[Dict[str, Any]]:
        """
        Playlist veya tekil video linkinden video listesini ayıklar.
        Her video için id, title, url ve duration döner.
        """
        if not yt_dlp:
            raise RuntimeError("yt-dlp kütüphanesi kurulu değil! 'pip install yt-dlp' çalıştırın.")

        ydl_opts = self._get_base_ydl_opts()
        ydl_opts["extract_flat"] = True  # Videoları indirmeden hızlı metadata al

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            videos = []
            if "entries" in info:
                # Oynatma listesi
                for entry in info["entries"]:
                    if entry:
                        video_id = entry.get("id")
                        title = entry.get("title", f"Video_{video_id}")
                        video_url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
                        videos.append({
                            "id": video_id,
                            "title": title,
                            "url": video_url,
                            "duration": entry.get("duration", 0)
                        })
            else:
                # Tek bir video
                video_id = info.get("id")
                title = info.get("title", f"Video_{video_id}")
                video_url = info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"
                videos.append({
                    "id": video_id,
                    "title": title,
                    "url": video_url,
                    "duration": info.get("duration", 0)
                })

            return videos

    def download_proxy_video(self, video_url: str, video_id: str) -> Path:
        """
        Sahne tespiti ve yüz analizi için videonun hızlı ve düşük çözünürlüklü (360p)
        geçici bir kopyasını indirir. Bu sayede 1-2 saatlik bölüm saniyeler içinde analiz edilir.
        """
        proxy_path = self.config.temp_dir / f"{video_id}_proxy_{self.config.proxy_height}p.mp4"
        if proxy_path.exists() and proxy_path.stat().st_size > 1024 * 1024:
            return proxy_path

        # Playlist linki verilmiş olsa bile yalnızca o tek videoyu indir
        target_url = f"https://www.youtube.com/watch?v={video_id}" if video_id and not video_id.startswith("preview") and len(video_id) == 11 else video_url

        ydl_opts = self._get_base_ydl_opts()
        ydl_opts.update({
            "noplaylist": True,
            # En düşük veriyle en hızlı analizi sağlamak için 360p video seçimi
            "format": f"bestvideo[height<={self.config.proxy_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={self.config.proxy_height}]/worst",
            "outtmpl": str(proxy_path.with_suffix("")),
            "merge_output_format": "mp4",
            "overwrites": True,
            "quiet": False,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([target_url])

        if not proxy_path.exists():
            # yt-dlp uzantıyı otomatik eklemiş olabilir
            candidates = list(self.config.temp_dir.glob(f"{video_id}_proxy_{self.config.proxy_height}p*"))
            if candidates:
                return candidates[0]
            raise FileNotFoundError(f"Proxy video indirilemedi: {video_url}")

        return proxy_path

    def download_exact_scene_section(
        self,
        video_url: str,
        start_sec: float,
        end_sec: float,
        output_filename: str
    ) -> Path:
        """
        Tüm videoyu baştan indirmeden, doğrudan YouTube üzerinden yalnızca onaylanan sahneyi
        en yüksek kalitede (1080p/2K/4K) keserek indirir.
        yt-dlp'nin '--download-sections' ve FFmpeg altyapısını kullanır.
        """
        output_file = self.config.output_dir / output_filename
        if output_file.exists():
            return output_file

        start_time_str = format_timestamp(start_sec)
        end_time_str = format_timestamp(end_sec)
        section_filter = f"*{start_time_str}-{end_time_str}"

        # yt-dlp python API ile download_ranges seçeneği
        ydl_opts = self._get_base_ydl_opts()
        ydl_opts.update({
            "noplaylist": True,
            "format": self.config.final_video_quality,
            "outtmpl": str(output_file.with_suffix("")),
            "merge_output_format": "mp4",
            "download_ranges": yt_dlp.utils.download_range_func(None, [(start_sec, end_sec)]),
            "force_keyframes_at_cuts": True,
            "quiet": False,
            "postprocessor_args": {
                "ffmpeg": ["-c:v", "libx264", "-c:a", "aac"]
            }
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
        except Exception:
            # Python API download_ranges bazı yt-dlp sürümlerinde CLI kadar esnek olmayabilir,
            # bu nedenle tam senkron CLI komutu fallback olarak çağrılır:
            self._download_section_cli_fallback(video_url, start_time_str, end_time_str, output_file)

        if not output_file.exists():
            candidates = list(self.config.output_dir.glob(f"{output_file.stem}*"))
            if candidates:
                return candidates[0]

        return output_file

    def _download_section_cli_fallback(
        self,
        video_url: str,
        start_str: str,
        end_str: str,
        output_path: Path
    ) -> None:
        """yt-dlp CLI komutu üzerinden hatasız section download fallback."""
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--download-sections", f"*{start_str}-{end_str}",
            "--force-keyframes-at-cuts",
            "-f", self.config.final_video_quality,
            "--merge-output-format", "mp4",
            "-o", str(output_path),
        ]
        if self.config.cookies_file:
            cmd.extend(["--cookies", self.config.cookies_file])
        elif self.config.cookies_browser:
            cmd.extend(["--cookies-from-browser", self.config.cookies_browser])

        cmd.append(video_url)
        subprocess.run(cmd, check=True)
