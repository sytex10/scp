"""
AI Scenepack Maker - Yüz Tanıma & Eşleştirme Motoru
Desteklenen Motorlar: DeepFace (TensorFlow/PyTorch/OpenCV) ve face_recognition (dlib)
"""

import os
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional
import cv2
import numpy as np

from config import ScenepackConfig
from scene_detector import SceneItem

def cosine_distance(source_rep: np.ndarray, test_rep: np.ndarray) -> float:
    """İki yüz embedding vektörü arasındaki Cosine mesafesini hesaplar."""
    a = np.asarray(source_rep, dtype=np.float32)
    b = np.asarray(test_rep, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return float(1.0 - np.dot(a, b) / denom)

class FaceMatcherEngine:
    def __init__(self, config: ScenepackConfig):
        self.config = config
        self.characters: Dict[str, List[np.ndarray]] = {}  # { "Polat": [emb1, emb2], "Cakir": [emb1] }
        self._init_engine()

    def _init_engine(self):
        """Seçili yüz tanıma kütüphanesinin hazır olup olmadığını kontrol eder."""
        self.engine_type = self.config.face_engine.lower()
        if self.engine_type == "deepface":
            try:
                import deepface.DeepFace as DeepFace
                self.deepface = DeepFace
            except ImportError:
                print("[BİLGİ] DeepFace yüklenemedi, 'face_recognition' motoruna geçiliyor.")
                self.engine_type = "face_recognition"

        if self.engine_type == "face_recognition":
            try:
                import face_recognition
                self.face_rec = face_recognition
            except ImportError:
                if not hasattr(self, 'deepface'):
                    raise ImportError("Ne 'deepface' ne de 'face_recognition' kütüphanesi bulundu! 'pip install deepface' çalıştırın.")

    def register_character(self, character_name: str, image_paths: List[Path]) -> int:
        """
        Hedef karakter için bir veya birden fazla referans fotoğraf yükler
        ve yüz embedding (sayısal yüz izi) vektörlerini çıkarır.
        """
        embeddings: List[np.ndarray] = []

        for img_path in image_paths:
            if not img_path.exists():
                print(f"[UYARI] Referans fotoğraf bulunamadı: {img_path}")
                continue

            try:
                if self.engine_type == "deepface":
                    # DeepFace ile yüz embedding çıkarma
                    reps = self.deepface.represent(
                        img_path=str(img_path),
                        model_name=self.config.deepface_model,
                        detector_backend=self.config.deepface_detector,
                        enforce_detection=False
                    )
                    for item in reps:
                        emb = np.array(item["embedding"], dtype=np.float32)
                        embeddings.append(emb)

                elif self.engine_type == "face_recognition":
                    # face_recognition (dlib) ile 128-boyutlu embedding
                    image = self.face_rec.load_image_file(str(img_path))
                    encs = self.face_rec.face_encodings(image)
                    for enc in encs:
                        embeddings.append(np.array(enc, dtype=np.float32))

            except Exception as e:
                print(f"[HATA] {img_path} taranırken sorun oluştu: {e}")

        if embeddings:
            self.characters[character_name] = embeddings
            print(f"[BAŞARILI] '{character_name}' için {len(embeddings)} yüz vektörü kaydedildi.")
        else:
            print(f"[UYARI] '{character_name}' için geçerli yüz tespit edilemedi!")

        return len(embeddings)

    def extract_scene_frames(self, video_path: Path, scene: SceneItem) -> List[Tuple[float, np.ndarray]]:
        """
        Belirli bir sahne zaman aralığından (start_sec -> end_sec)
        yapılandırılan saniye başı örneklem (sample_fps) kadar kareyi OpenCV ile çeker.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        sampled_frames: List[Tuple[float, np.ndarray]] = []
        duration = scene.duration_sec
        interval = 1.0 / max(self.config.sample_fps, 0.2)  # Örn: 1.0 saniye aralık

        curr_time = scene.start_sec + 0.3  # Sahne başındaki ilk geçiş karesini atla
        while curr_time < (scene.end_sec - 0.2):
            cap.set(cv2.CAP_PROP_POS_MSEC, curr_time * 1000.0)
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            sampled_frames.append((curr_time, frame))
            curr_time += interval

        cap.release()
        return sampled_frames

    def analyze_frame_faces(self, frame: np.ndarray) -> List[np.ndarray]:
        """Tek bir karede bulunan tüm yüzlerin embedding vektörlerini döner."""
        frame_embeddings: List[np.ndarray] = []

        try:
            if self.engine_type == "deepface":
                reps = self.deepface.represent(
                    img_path=frame,
                    model_name=self.config.deepface_model,
                    detector_backend=self.config.deepface_detector,
                    enforce_detection=False
                )
                frame_h, frame_w = frame.shape[:2]
                for item in reps:
                    # Yüzün gerçekliğini ve geçerliliğini sıkı denetle
                    confidence = item.get("confidence")
                    area = item.get("facial_area", {})
                    w = area.get("w", 0)
                    h = area.get("h", 0)
                    
                    # 1. Eğer yüz bulunamadıysa DeepFace confidence'ı None döner veya tüm kareyi verir (0.0)
                    if confidence is None or (isinstance(confidence, (int, float)) and confidence < 0.55):
                        continue
                        
                    # 2. Tüm ekranın veya çok küçük parazitlerin sahte yüz sayılmasını engelle
                    if w < 28 or h < 28:
                        continue
                    if w > (frame_w * 0.85) and h > (frame_h * 0.85):
                        continue

                    # 3. YuNet göz noktası kontrolü (gerçek insan yüzü filtresi)
                    if self.config.deepface_detector.lower() == "yunet" and area.get("left_eye") is None:
                        continue

                    frame_embeddings.append(np.array(item["embedding"], dtype=np.float32))

            elif self.engine_type == "face_recognition":
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                encs = self.face_rec.face_encodings(rgb_frame)
                for enc in encs:
                    frame_embeddings.append(np.array(enc, dtype=np.float32))

        except Exception:
            pass

        return frame_embeddings

    def match_scene(self, video_path: Path, scene: SceneItem) -> Dict[str, Any]:
        """
        Sahneden örnek kareleri tarar ve hedef karakterlerle eşleşip eşleşmediğini
        AND / OR mantığına göre değerlendirir.
        """
        sampled_frames = self.extract_scene_frames(video_path, scene)
        if not sampled_frames:
            return {"matched": False, "characters": [], "stats": {}}

        char_matches: Dict[str, int] = {c: 0 for c in self.characters}
        char_best_distance: Dict[str, float] = {c: 1.0 for c in self.characters}
        simultaneous_co_presence = False

        for timestamp, frame in sampled_frames:
            frame_embeddings = self.analyze_frame_faces(frame)
            if not frame_embeddings:
                continue

            frame_chars_found = set()

            for frame_emb in frame_embeddings:
                for char_name, ref_embs in self.characters.items():
                    for ref_emb in ref_embs:
                        dist = cosine_distance(ref_emb, frame_emb)
                        if dist < char_best_distance[char_name]:
                            char_best_distance[char_name] = dist

                        # Mesafe eşikten küçükse pozitif eşleşme
                        if dist <= self.config.cosine_threshold:
                            frame_chars_found.add(char_name)
                            break

            for matched_char in frame_chars_found:
                char_matches[matched_char] += 1

            # Aynı karede ikisi birden var mı?
            if len(self.characters) > 1 and len(frame_chars_found) >= 2:
                simultaneous_co_presence = True

        # Karakterlerin bu sahnede onaylanma kriteri:
        # Sahne kısa ise (<= 3 kare) en az 1 kare yeterli; 4+ kare varsa en az 2 karede net görünmeli!
        required_hits = 1 if len(sampled_frames) <= 3 else max(2, self.config.min_matching_frames)
        confirmed_chars = [
            c for c, count in char_matches.items()
            if count >= required_hits
        ]

        # Mantıksal Değerlendirme (OR / AND)
        is_matched = False
        if self.config.match_logic.upper() == "OR":
            is_matched = len(confirmed_chars) >= 1
        elif self.config.match_logic.upper() == "AND":
            if self.config.co_presence_in_same_frame:
                is_matched = simultaneous_co_presence
            else:
                # İkisi de sahne içinde bulunduysa (diyalog kesmeleri dahil)
                is_matched = len(confirmed_chars) >= len(self.characters)

        return {
            "matched": is_matched,
            "characters": confirmed_chars,
            "matches_count": char_matches,
            "best_distance": char_best_distance,
            "simultaneous_co_presence": simultaneous_co_presence,
            "total_samples": len(sampled_frames)
        }
