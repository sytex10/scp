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

    def download_master_video(self, video_url: str, video_id: str, quality: str = "1080p") -> Path:
        """
        Sahne kesimleri için ana videoyu tek seferde yüksek kalitede indirir.
        Bu sayede 30-50 sahne için YouTube'a 50 kez bağlanıp beklemek yerine,
        video 1 kez hızlıca indirilir ve tüm sahneler milisaniyeler içinde kesilir.
        """
        master_path = self.config.temp_dir / f"{video_id}_master_{quality}.mp4"
        if master_path.exists() and master_path.stat().st_size > 10 * 1024 * 1024:
            return master_path

        target_url = f"https://www.youtube.com/watch?v={video_id}" if video_id and not video_id.startswith("preview") and len(video_id) == 11 else video_url

        fmt = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
        if quality == "720p":
            fmt = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best"
        elif quality == "best":
            fmt = "bestvideo+bestaudio/best"

        ydl_opts = self._get_base_ydl_opts()
        ydl_opts.update({
            "noplaylist": True,
            "format": fmt,
            "outtmpl": str(master_path.with_suffix("")),
            "merge_output_format": "mp4",
            "overwrites": True,
            "quiet": False,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([target_url])

        if not master_path.exists():
            candidates = list(self.config.temp_dir.glob(f"{video_id}_master_{quality}*"))
            if candidates:
                return candidates[0]
            raise FileNotFoundError(f"Master video indirilemedi: {video_url}")

        return master_path

    def cut_scene_from_local(
        self,
        source_path: Path,
        start_sec: float,
        end_sec: float,
        output_filename: str
    ) -> Path:
        """
        Yerel master videodan belirtilen sahneyi FFmpeg ile milisaniyeler içinde keser.
        Stream Copy (-c copy) kullanarak CPU yükünü ve saatlerce süren render beklemelerini sıfıra indirir.
        """
        output_file = self.config.output_dir / output_filename
        if output_file.exists() and output_file.stat().st_size > 10000:
            return output_file

        start_str = format_timestamp(start_sec)
        dur_sec = max(0.5, end_sec - start_sec)

        # 1. Ultra-hızlı Stream Copy (-c copy)
        cmd_copy = [
            "ffmpeg", "-y",
            "-ss", start_str,
            "-i", str(source_path),
            "-t", f"{dur_sec:.3f}",
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(output_file)
        ]
        subprocess.run(cmd_copy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2. Keyframe uyuşmazlığı varsa ultrafast x264 ile anında tamamla (0.3 saniye)
        if not output_file.exists() or output_file.stat().st_size < 10000:
            cmd_fast = [
                "ffmpeg", "-y",
                "-ss", start_str,
                "-i", str(source_path),
                "-t", f"{dur_sec:.3f}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                "-c:a", "aac",
                str(output_file)
            ]
            subprocess.run(cmd_fast, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return output_file

    def download_exact_scene_section(
        self,
        video_url: str,
        start_sec: float,
        end_sec: float,
        output_filename: str
    ) -> Path:
        """Tekil sahne indirme fallback metodu."""
        output_file = self.config.output_dir / output_filename
        if output_file.exists():
            return output_file

        start_time_str = format_timestamp(start_sec)
        end_time_str = format_timestamp(end_sec)
        section_filter = f"*{start_time_str}-{end_time_str}"

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
                "ffmpeg": ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"]
            }
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
        except Exception:
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
