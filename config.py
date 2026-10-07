"""
AI Scenepack Maker - Yapılandırma ve Varsayılan Ayarlar
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

@dataclass
class ScenepackConfig:
    # --- Giriş & Çıkış Yolları ---
    output_dir: Path = Path("output_scenepacks")
    temp_dir: Path = Path("temp_cache")
    
    # --- Analiz & Proxy Akışı (Hızlı Tarama) ---
    # Tam videoyu 1080p/4K indirmeden sahne tespiti için geçici düşük çözünürlük
    proxy_height: int = 360  # 360p veya 480p
    
    # --- Sahne Algılama (PySceneDetect) Ayarları ---
    scene_threshold: float = 27.0  # ContentDetector eşiği (standart 25.0 - 30.0)
    min_scene_duration_sec: float = 2.0  # Bu süreden kısa sahneler filtrelenir
    
    # --- Kare Örnekleme (Sample Rate) ---
    # Her sahnenin içerisinden saniyede kaç kare alınıp yüz taramasına sokulacak
    sample_fps: float = 1.0  # 1.0 = her saniyeden 1 kare (performans ve doğruluk dengesi)
    min_matching_frames: int = 2  # Bir sahnede karakterin onaylanması için en az kaç karede bulunmalı (yanlış eşleşmeleri engeller)
    
    # --- Yüz Tanıma & Yapay Zeka Motoru ---
    face_engine: str = "deepface"  # 'deepface' veya 'face_recognition'
    deepface_model: str = "Facenet512"  # 'Facenet512', 'VGG-Face', 'ArcFace', 'SFace'
    deepface_detector: str = "yunet"  # 'yunet' (OpenCV C++ DNN destekli ultra hızlı & hatasız yüz tespiti)
    similarity_metric: str = "cosine"  # 'cosine', 'euclidean'
    cosine_threshold: float = 0.32  # Facenet512 için cosine distance <= 0.32 = Gerçek Eşleşme (0.40 alakasız yüzleri alıyordu)
    
    # --- Eşleşme Mantığı ---
    # 'OR' = Karakter 1 VEYA Karakter 2'nin olduğu sahneler
    # 'AND' = İkisinin aynı sahnede (veya aynı karede) olduğu sahneler
    match_logic: str = "OR"
    co_presence_in_same_frame: bool = False  # AND modunda aynı karede yan yana olmalarını zorunlu kıl
    
    # --- Nihai Çıktı Kalitesi ---
    # YouTube'dan kesilen sahnenin kalitesi
    final_video_quality: str = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    
    # --- YouTube & yt-dlp Ayarları ---
    cookies_file: Optional[str] = None  # Örn: cookies.txt (Bot engeli veya 18+ videolar için)
    cookies_browser: Optional[str] = None  # Örn: 'chrome', 'firefox', 'edge'
    keep_proxy: bool = False  # Analiz sonrası geçici 360p dosyasını sil/tut
    concurrent_downloads: int = 2
