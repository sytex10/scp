"""
AI Scenepack Maker - Sahne Değişimi Algılama (PySceneDetect Motoru)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple
import cv2

try:
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector, AdaptiveDetector
    SCENEDETECT_AVAILABLE = True
except ImportError:
    SCENEDETECT_AVAILABLE = False

from config import ScenepackConfig

@dataclass
class SceneItem:
    scene_index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    start_frame: int
    end_frame: int

class SceneDetectorEngine:
    def __init__(self, config: ScenepackConfig):
        self.config = config

    def detect_scenes(self, video_path: Path) -> List[SceneItem]:
        """
        PySceneDetect kullanarak video içindeki tüm sahne geçişlerini ve
        kamera açısı değişimlerini saniyesi saniyesine çıkarır.
        """
        if not SCENEDETECT_AVAILABLE:
            print("[UYARI] 'scenedetect' kütüphanesi bulunamadı! OpenCV tabanlı alternatif sahne tespiti çalıştırılıyor...")
            return self._detect_scenes_opencv_fallback(video_path)

        # PySceneDetect ile optimize video açma
        video = open_video(str(video_path))
        scene_manager = SceneManager()
        
        # Kamera kesmelerini yakalamak için ContentDetector
        detector = ContentDetector(
            threshold=self.config.scene_threshold,
            min_scene_len=int(self.config.min_scene_duration_sec * video.frame_rate)
        )
        scene_manager.add_detector(detector)

        # Videoyu sahnelere ayır
        scene_manager.detect_scenes(video)
        scene_list = scene_manager.get_scene_list()

        results: List[SceneItem] = []
        for idx, (start_tc, end_tc) in enumerate(scene_list, start=1):
            start_sec = start_tc.get_seconds()
            end_sec = end_tc.get_seconds()
            duration = end_sec - start_sec

            if duration >= self.config.min_scene_duration_sec:
                results.append(
                    SceneItem(
                        scene_index=idx,
                        start_sec=start_sec,
                        end_sec=end_sec,
                        duration_sec=duration,
                        start_frame=start_tc.get_frames(),
                        end_frame=end_tc.get_frames(),
                    )
                )

        # Eğer hiç sahne bölünmediyse (örneğin tek kesintisiz çekim), tüm videoyu tek sahne kabul et
        if not results:
            total_frames = int(video.duration.get_frames())
            total_sec = video.duration.get_seconds()
            results.append(
                SceneItem(
                    scene_index=1,
                    start_sec=0.0,
                    end_sec=total_sec,
                    duration_sec=total_sec,
                    start_frame=0,
                    end_frame=total_frames,
                )
            )

        return results

    def _detect_scenes_opencv_fallback(self, video_path: Path) -> List[SceneItem]:
        """scenedetect kütüphanesi olmadan çalışan OpenCV renk farkı (histogram) tabanlı sahne tespiti."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Video açılamadı: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        min_frame_dist = int(fps * self.config.min_scene_duration_sec)

        prev_hist = None
        cut_frames = [0]
        frame_idx = 0

        # Hızlı tarama için her 2 karede bir bak
        step = 2
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step == 0:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

                if prev_hist is not None:
                    # Histogram korelasyonu (0.45'ten küçükse sahne değişmiştir)
                    corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                    if corr < 0.45 and (frame_idx - cut_frames[-1]) >= min_frame_dist:
                        cut_frames.append(frame_idx)
                prev_hist = hist

            frame_idx += 1

        cap.release()
        if cut_frames[-1] < total_frames:
            cut_frames.append(total_frames)

        results: List[SceneItem] = []
        for i in range(len(cut_frames) - 1):
            sf = cut_frames[i]
            ef = cut_frames[i + 1]
            s_sec = sf / fps
            e_sec = ef / fps
            dur = e_sec - s_sec
            if dur >= self.config.min_scene_duration_sec:
                results.append(
                    SceneItem(
                        scene_index=i + 1,
                        start_sec=s_sec,
                        end_sec=e_sec,
                        duration_sec=dur,
                        start_frame=sf,
                        end_frame=ef,
                    )
                )

        return results
