"""
AI Scenepack Maker - Modern Web & Masaüstü Kullanıcı Arayüzü (Flask Sunucusu)
Kullanıcıların tarayıcı üzerinden YouTube linki verip, doğrudan video içinden
karakterleri tıklayarak seçebildiği ve anlık ilerlemeyi izlediği kontrol paneli.
"""

from __future__ import annotations
import os
import sys
import json
import base64
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List

import cv2
import numpy as np
from flask import Flask, render_template, request, jsonify, send_from_directory

from config import ScenepackConfig
from downloader import YouTubeMediaEngine, sanitize_filename, format_timestamp
from scene_detector import SceneDetectorEngine, SceneItem
from face_matcher import FaceMatcherEngine
from face_picker import VideoFacePicker

# Windows terminal UTF-8 uyumu
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

app = Flask(__name__, template_folder="templates")
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

BASE_DIR = Path(__file__).parent.resolve()
DEFAULT_DESKTOP_OUTPUT = Path.home() / "Desktop" / "Scenepacks"
CONFIG = ScenepackConfig(
    output_dir=DEFAULT_DESKTOP_OUTPUT,
    temp_dir=BASE_DIR / "temp_cache"
)
CONFIG.output_dir.mkdir(parents=True, exist_ok=True)
MEDIA_ENGINE = YouTubeMediaEngine(CONFIG)
FACE_PICKER = VideoFacePicker(characters_base_dir=BASE_DIR / "characters")

# Küresel Görev Durumu (Arka plan işlemi takibi)
TASK_STATE: Dict[str, Any] = {
    "status": "idle",       # "idle", "running", "completed", "error"
    "step_name": "",        # "Hazırlanıyor", "Proxy İndiriliyor", "Sahne Tespiti", "Yüz Taraması", "Sahneler Kesiliyor"
    "progress_pct": 0,
    "current_video": "",
    "total_scenes": 0,
    "scanned_scenes": 0,
    "matched_scenes": [],
    "exported_files": [],
    "logs": [],
    "error": None
}

def add_log(msg: str):
    TASK_STATE["logs"].append(msg)
    if len(TASK_STATE["logs"]) > 100:
        TASK_STATE["logs"].pop(0)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/inspect-url", methods=["POST"])
def inspect_url():
    """Girilen YouTube linkinin geçerliliğini ve video listesini döner."""
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Geçerli bir YouTube linki girin."}), 400

    try:
        videos = MEDIA_ENGINE.extract_playlist_info(url)
        formatted_videos = []
        for idx, v in enumerate(videos, start=1):
            dur = v.get("duration", 0) or 0
            formatted_videos.append({
                "index": idx,
                "id": v.get("id"),
                "title": v.get("title", f"Video #{idx}"),
                "url": v.get("url"),
                "duration": dur,
                "duration_formatted": f"{int(dur // 60):02d}:{int(dur % 60):02d}" if dur else "--:--"
            })
        return jsonify({
            "success": True,
            "count": len(videos),
            "videos": formatted_videos
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/prepare-proxy", methods=["POST"])
def prepare_proxy():
    """Video içinden yüz seçebilmek için hızlı 360p proxy videosunu hazırlar."""
    data = request.json or {}
    url = data.get("url", "").strip()
    video_id = data.get("id", "").strip()

    if not url:
        return jsonify({"error": "URL eksik."}), 400

    try:
        proxy_path = MEDIA_ENGINE.download_proxy_video(url, video_id or "preview_video")
        cap = cv2.VideoCapture(str(proxy_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        cap.release()

        return jsonify({
            "success": True,
            "proxy_filename": proxy_path.name,
            "video_url": f"/temp_cache/{proxy_path.name}",
            "duration": duration,
            "duration_formatted": f"{int(duration // 60):02d}:{int(duration % 60):02d}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/temp_cache/<path:filename>")
def serve_temp_cache(filename):
    """Proxy videolarını tarayıcıda akıcı oynatmak için Range destekli sunar."""
    return send_from_directory(str(CONFIG.temp_dir), filename, conditional=True)

@app.route("/api/extract-faces-at-time", methods=["POST"])
def extract_faces_at_time():
    """Kullanıcının zaman çubuğundan seçtiği saniyedeki yüzleri tespit edip döner."""
    data = request.json or {}
    proxy_filename = data.get("proxy_filename", "")
    timestamp_sec = float(data.get("timestamp_sec", 0.0))

    proxy_path = CONFIG.temp_dir / proxy_filename
    if not proxy_path.exists():
        return jsonify({"error": "Proxy video bulunamadı, önce videoyu hazırlayın."}), 404

    cap = cv2.VideoCapture(str(proxy_path))
    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000.0)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return jsonify({"error": "Bu saniyeden kare alınamadı."}), 400

    # Yüzleri tespit et
    faces_bbox = FACE_PICKER.detect_faces_in_frame(frame)
    faces_data = []

    h, w, _ = frame.shape
    for idx, (fx, fy, fw, fh) in enumerate(faces_bbox):
        # Yüz payı ekle
        margin_x = int(fw * 0.2)
        margin_y = int(fh * 0.2)
        x1 = max(0, fx - margin_x)
        y1 = max(0, fy - margin_y)
        x2 = min(w, fx + fw + margin_x)
        y2 = min(h, fy + fh + margin_y)

        crop = frame[y1:y2, x1:x2]
        _, buffer = cv2.imencode(".jpg", crop)
        b64_crop = base64.b64encode(buffer).decode("utf-8")

        faces_data.append({
            "index": idx + 1,
            "bbox": [int(fx), int(fy), int(fw), int(fh)],
            "image_b64": f"data:image/jpeg;base64,{b64_crop}"
        })

    # Tam kareyi de dön
    _, full_buf = cv2.imencode(".jpg", frame)
    b64_full = base64.b64encode(full_buf).decode("utf-8")

    return jsonify({
        "success": True,
        "timestamp_sec": timestamp_sec,
        "faces": faces_data,
        "full_frame_b64": f"data:image/jpeg;base64,{b64_full}"
    })

# İptal Bayrağı
CANCEL_FLAG = threading.Event()

def normalize_character_name(name: str) -> str:
    """Türkçe karakterleri dosya sistemiyle uyumlu hale getirir (örn: Çakır -> Cakir)."""
    tr_map = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOsSuU")
    clean = name.translate(tr_map).strip()
    return re.sub(r'[\\/*?:"<>|]', "", clean).strip().replace(" ", "_")

@app.route("/api/save-character-face", methods=["POST"])
def save_character_face():
    """Seçilen yüzü belirli bir karakter adı altına kaydeder."""
    data = request.json or {}
    raw_name = data.get("character_name", "").strip()
    image_b64 = data.get("image_b64", "")

    if not raw_name or not image_b64:
        return jsonify({"error": "Karakter adı ve görsel zorunludur."}), 400

    clean_name = normalize_character_name(raw_name)
    char_dir = BASE_DIR / "characters" / clean_name
    char_dir.mkdir(parents=True, exist_ok=True)

    header, encoded = image_b64.split(",", 1) if "," in image_b64 else ("", image_b64)
    file_bytes = base64.b64decode(encoded)

    existing = len(list(char_dir.glob("ref_*.jpg")))
    save_path = char_dir / f"ref_{existing + 1}.jpg"
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    return jsonify({
        "success": True,
        "character_name": clean_name,
        "saved_path": str(save_path),
        "total_images": len(list(char_dir.glob("ref_*.jpg")))
    })

@app.route("/api/characters", methods=["GET"])
def get_characters():
    """Kayıtlı karakterleri ve her birinin tüm referans fotoğraflarını listeler."""
    chars_base = BASE_DIR / "characters"
    chars_base.mkdir(parents=True, exist_ok=True)

    characters = []
    for sub in sorted(chars_base.iterdir()):
        if sub.is_dir():
            imgs = sorted(
                [p for p in sub.iterdir() if p.suffix.lower() in {".jpg", ".png", ".jpeg", ".webp"}],
                key=lambda x: x.stat().st_mtime
            )
            if imgs:
                images_list = []
                for img_p in imgs:
                    try:
                        with open(img_p, "rb") as f:
                            b64_img = base64.b64encode(f.read()).decode("utf-8")
                        images_list.append({
                            "filename": img_p.name,
                            "thumbnail": f"data:image/jpeg;base64,{b64_img}"
                        })
                    except Exception:
                        pass

                characters.append({
                    "name": sub.name,
                    "image_count": len(images_list),
                    "images": images_list
                })

    return jsonify({"characters": characters})

@app.route("/api/delete-character-image", methods=["POST"])
def delete_character_image():
    """Belirli bir karakterin tek bir referans fotoğrafını siler."""
    data = request.json or {}
    char_name = data.get("character_name", "").strip()
    filename = data.get("filename", "").strip()

    target_file = BASE_DIR / "characters" / char_name / filename
    if target_file.exists() and target_file.is_file():
        try:
            target_file.unlink()
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Fotoğraf bulunamadı."}), 404

@app.route("/api/delete-character", methods=["POST"])
def delete_character():
    """Karakter klasörünü ve tüm fotoğraflarını siler."""
    data = request.json or {}
    char_name = data.get("name", "").strip()
    char_dir = BASE_DIR / "characters" / char_name
    if char_dir.exists() and char_dir.is_dir():
        for f in char_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass
        try:
            char_dir.rmdir()
        except Exception:
            pass
    return jsonify({"success": True})

@app.route("/api/cancel-task", methods=["POST"])
def cancel_task():
    """Devam eden sahne tarama ve kesme işlemini durdurur."""
    global CANCEL_FLAG
    CANCEL_FLAG.set()
    TASK_STATE["status"] = "idle"
    TASK_STATE["step_name"] = "İptal Edildi"
    add_log("[İPTAL] Kullanıcı işlemi durdurdu.")
    return jsonify({"success": True})

@app.route("/api/open-folder", methods=["POST"])
def open_output_folder():
    """Çıktı klasörünü işletim sistemi dosya gezgininde açar."""
    out_dir = Path(CONFIG.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            # 1. os.startfile (ShellExecute)
            try:
                os.startfile(str(out_dir))
            except Exception:
                pass
            # 2. Doğrudan explorer.exe çağrısı
            try:
                subprocess.Popen(["explorer.exe", str(out_dir)])
            except Exception:
                pass
            # 3. PowerShell Start-Process explorer.exe ile yeni pencereyi zorla aç
            try:
                subprocess.Popen([
                    "powershell", "-NoProfile", "-Command",
                    f"Start-Process explorer.exe -ArgumentList '/n,`\"{str(out_dir)}`\"'"
                ])
            except Exception:
                pass
            # 4. Shell.Application COM
            try:
                subprocess.Popen(["powershell", "-NoProfile", "-Command", f'(New-Object -ComObject Shell.Application).Explore("{str(out_dir)}")'])
            except Exception:
                pass
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(out_dir)])
        else:
            subprocess.Popen(["xdg-open", str(out_dir)])
        return jsonify({"success": True, "path": str(out_dir)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/output-files", methods=["GET"])
def get_output_files():
    """Çıktı klasöründeki MP4 dosyalarını listeler."""
    out_dir = Path(CONFIG.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(out_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({
            "name": f.name,
            "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
            "url": f"/download/{f.name}"
        })
    return jsonify({
        "path": str(out_dir),
        "files": files
    })

@app.route("/download/<path:filename>")
def download_output_file(filename):
    """Çıktı klasöründeki dosyayı doğrudan indirme veya tarayıcıda oynatma."""
    out_dir = Path(CONFIG.output_dir).resolve()
    return send_from_directory(out_dir, filename, as_attachment=False)

@app.route("/api/get-settings", methods=["GET"])
def get_settings():
    """Mevcut ayarları ve hazır klasör yollarını döner."""
    desktop = (Path.home() / "Desktop" / "Scenepacks").resolve()
    videos = (Path.home() / "Videos" / "Scenepacks").resolve()
    downloads = (Path.home() / "Downloads" / "Scenepacks").resolve()
    project = (BASE_DIR / "output_scenepacks").resolve()
    return jsonify({
        "output_dir": str(CONFIG.output_dir.resolve()),
        "desktop_dir": str(desktop),
        "videos_dir": str(videos),
        "downloads_dir": str(downloads),
        "project_dir": str(project)
    })

@app.route("/api/set-output-dir", methods=["POST"])
def set_output_dir():
    """Kullanıcının belirlediği çıktı klasörünü günceller."""
    data = request.json or {}
    new_dir = data.get("output_dir", "").strip()
    if not new_dir:
        return jsonify({"error": "Geçerli bir klasör yolu giriniz."}), 400
    try:
        p = Path(new_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        CONFIG.output_dir = p
        return jsonify({"success": True, "output_dir": str(p)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_scenepack_thread(url: str, match_logic: str, min_duration: float, quality: str, selected_indices: Optional[List[int]] = None, custom_output_dir: Optional[str] = None):
    """Arka planda çalışan asenkron sahne kesme işlemi."""
    global TASK_STATE
    try:
        if custom_output_dir:
            try:
                p = Path(custom_output_dir).resolve()
                p.mkdir(parents=True, exist_ok=True)
                CONFIG.output_dir = p
            except Exception:
                pass

        TASK_STATE["status"] = "running"
        TASK_STATE["progress_pct"] = 0
        TASK_STATE["matched_scenes"] = []
        TASK_STATE["exported_files"] = []
        TASK_STATE["logs"] = []
        TASK_STATE["error"] = None

        config = ScenepackConfig(
            output_dir=CONFIG.output_dir,
            temp_dir=CONFIG.temp_dir,
            match_logic=match_logic.upper(),
            min_scene_duration_sec=min_duration
        )
        if quality == "1080p":
            config.final_video_quality = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best"
        elif quality == "720p":
            config.final_video_quality = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best"
        elif quality == "best":
            config.final_video_quality = "bestvideo+bestaudio/best"

        engine = YouTubeMediaEngine(config)
        scene_engine = SceneDetectorEngine(config)
        face_matcher = FaceMatcherEngine(config)

        # Karakterleri yükle
        chars_base = BASE_DIR / "characters"
        char_count = 0
        for sub in chars_base.iterdir():
            if sub.is_dir():
                imgs = [p for p in sub.iterdir() if p.suffix.lower() in {".jpg", ".png", ".jpeg"}]
                if imgs:
                    face_matcher.register_character(sub.name, imgs)
                    char_count += 1

        if char_count == 0:
            raise ValueError("Kayıtlı en az bir karakter bulunmalıdır!")

        add_log(f"Hedef Karakterler: {', '.join(face_matcher.characters.keys())}")
        TASK_STATE["step_name"] = "Video Bilgileri Çekiliyor..."
        all_videos = engine.extract_playlist_info(url)
        if selected_indices and len(all_videos) > 1:
            videos = [v for idx, v in enumerate(all_videos, start=1) if idx in selected_indices]
            add_log(f"Playlistten seçilen {len(videos)} / {len(all_videos)} video taranacak.")
        else:
            videos = all_videos
            add_log(f"Toplam {len(videos)} video taranacak.")

        for v_idx, video_info in enumerate(videos, start=1):
            if CANCEL_FLAG.is_set():
                add_log("[İPTAL] İşlem durduruldu.")
                return

            title = video_info["title"]
            vid_id = video_info["id"]
            vid_url = video_info["url"]
            clean_title = sanitize_filename(title)
            TASK_STATE["current_video"] = title

            # 1. 360p Proxy İndir
            TASK_STATE["step_name"] = f"[{v_idx}/{len(videos)}] 360p Proxy İndiriliyor..."
            add_log(f"{title}: Proxy indiriliyor...")
            proxy_path = engine.download_proxy_video(vid_url, vid_id)

            if CANCEL_FLAG.is_set():
                add_log("[İPTAL] İşlem durduruldu.")
                return

            # 2. Sahne Tespiti
            TASK_STATE["step_name"] = f"[{v_idx}/{len(videos)}] Sahne Geçişleri Tespit Ediliyor..."
            add_log(f"{title}: PySceneDetect çalıştırılıyor...")
            scenes = scene_engine.detect_scenes(proxy_path)
            TASK_STATE["total_scenes"] = len(scenes)
            TASK_STATE["scanned_scenes"] = 0
            add_log(f"{title}: {len(scenes)} sahne bulundu.")

            # 3. Yüz Tanıma & Analiz
            TASK_STATE["step_name"] = f"[{v_idx}/{len(videos)}] Yapay Zeka ile Yüzler Taranıyor..."
            matched_for_this_video = []

            for idx, sc in enumerate(scenes, start=1):
                if CANCEL_FLAG.is_set():
                    add_log("[İPTAL] Yüz taraması durduruldu.")
                    return

                TASK_STATE["scanned_scenes"] = idx
                TASK_STATE["progress_pct"] = int((idx / len(scenes)) * 70)  # %70'e kadar tarama

                match_res = face_matcher.match_scene(proxy_path, sc)
                if match_res["matched"]:
                    item = {
                        "video_title": title,
                        "scene_index": sc.scene_index,
                        "start_time": format_timestamp(sc.start_sec),
                        "end_time": format_timestamp(sc.end_sec),
                        "duration": f"{sc.duration_sec:.1f} sn",
                        "characters": match_res["characters"]
                    }
                    TASK_STATE["matched_scenes"].append(item)
                    matched_for_this_video.append((sc, match_res))
                    add_log(f"✔ Sahne {sc.scene_index} Eşleşti! ({', '.join(match_res['characters'])})")

            # 4. Ultra-Hızlı Kesme & Dışa Aktarma
            if matched_for_this_video:
                TASK_STATE["step_name"] = f"[{v_idx}/{len(videos)}] Yüksek Kalite Video İndiriliyor (Hızlı Kesim)..."
                add_log(f"⚡ {len(matched_for_this_video)} onaylı sahne bulundu! Yüksek kalite video tek seferde indiriliyor...")
                
                master_path = engine.download_master_video(vid_url, vid_id, quality)

                TASK_STATE["step_name"] = f"[{v_idx}/{len(videos)}] Sahneler Ultra-Hızlı Kesiliyor..."
                for s_idx, (sc, mres) in enumerate(matched_for_this_video, start=1):
                    if CANCEL_FLAG.is_set():
                        add_log("[İPTAL] Sahne kesimi durduruldu.")
                        return

                    chars_tag = "_".join(mres["characters"]) or "Match"
                    start_str_short = f"{int(sc.start_sec // 60):02d}m{int(sc.start_sec % 60):02d}s"
                    end_str_short = f"{int(sc.end_sec // 60):02d}m{int(sc.end_sec % 60):02d}s"
                    filename = f"Scenepack_{clean_title[:25]}_S{sc.scene_index:03d}_{chars_tag}_{start_str_short}-{end_str_short}.mp4"

                    add_log(f"✂ Kesiliyor ({s_idx}/{len(matched_for_this_video)}): {filename} ({sc.duration_sec:.1f} sn)")
                    cut_file = engine.cut_scene_from_local(
                        source_path=master_path,
                        start_sec=sc.start_sec,
                        end_sec=sc.end_sec,
                        output_filename=filename
                    )
                    TASK_STATE["exported_files"].append(cut_file.name)
                    pct = 70 + int((s_idx / len(matched_for_this_video)) * 30)
                    TASK_STATE["progress_pct"] = min(100, pct)

                # Geçici master videoyu sil (disk dolmasın)
                if not CONFIG.keep_proxy and master_path.exists():
                    try:
                        os.remove(master_path)
                    except Exception:
                        pass

            # Geçici proxy sil
            if proxy_path.exists():
                try:
                    os.remove(proxy_path)
                except Exception:
                    pass

        TASK_STATE["progress_pct"] = 100
        TASK_STATE["status"] = "completed"
        TASK_STATE["step_name"] = "Tamamlandı!"
        add_log(f"İşlem bitti! Toplam {len(TASK_STATE['exported_files'])} sahne oluşturuldu.")

    except Exception as e:
        TASK_STATE["status"] = "error"
        TASK_STATE["error"] = str(e)
        add_log(f"[HATA] {e}")

@app.route("/api/start-scenepack", methods=["POST"])
def start_scenepack():
    """Scenepack üretim görevini başlatır."""
    if TASK_STATE["status"] == "running":
        return jsonify({"error": "Şu anda zaten çalışan bir işlem var!"}), 400

    CANCEL_FLAG.clear()

    data = request.json or {}
    url = data.get("url", "").strip()
    match_logic = data.get("logic", "OR")
    min_duration = float(data.get("min_duration", 2.0))
    quality = data.get("quality", "1080p")
    selected_indices = data.get("selected_indices")
    if selected_indices and isinstance(selected_indices, list):
        try:
            selected_indices = [int(x) for x in selected_indices]
        except Exception:
            selected_indices = None
    else:
        selected_indices = None

    if not url:
        return jsonify({"error": "YouTube linki zorunludur."}), 400

    custom_dir = data.get("output_dir", "").strip()
    thread = threading.Thread(
        target=run_scenepack_thread,
        args=(url, match_logic, min_duration, quality, selected_indices, custom_dir),
        daemon=True
    )
    thread.start()

    return jsonify({"success": True, "message": "Scenepack işlemi arka planda başlatıldı."})

@app.route("/api/task-status", methods=["GET"])
def task_status():
    """Canlı işlem durumunu ve ilerlemeyi döner."""
    return jsonify(TASK_STATE)

@app.route("/output_scenepacks/<path:filename>")
def serve_output_file(filename):
    """Kesilen MP4 videolarını tarayıcıdan önizlemek için sunar."""
    return send_from_directory(str(CONFIG.output_dir.resolve()), filename)

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🎬 AI Scenepack Maker - Web Arayüzü Başlatıldı!")
    print("👉 Tarayıcınızda açın: http://localhost:5000")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
