"""
AI Scenepack Maker - Videodan Doğrudan Karakter/Yüz Seçici (Face Picker)
Kullanıcının harici fotoğraf aramasına gerek kalmadan, doğrudan video içinden
zaman damgasıyla veya interaktif pencereyle karakter yüzünü seçip kaydetmesini sağlar.
"""

from pathlib import Path
from typing import List, Dict, Tuple, Optional
import cv2
import numpy as np
from rich.console import Console
from rich.prompt import Prompt

console = Console()

class VideoFacePicker:
    def __init__(self, characters_base_dir: Path = Path("characters")):
        self.characters_base_dir = characters_base_dir
        self.characters_base_dir.mkdir(parents=True, exist_ok=True)
        self.face_cascade = None
        if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
            try:
                cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                self.face_cascade = cv2.CascadeClassifier(cascade_path)
            except Exception:
                self.face_cascade = None

    def detect_faces_in_frame(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Karedeki yüz koordinatlarını (x, y, w, h) döner."""
        if self.face_cascade is not None:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self.face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(30, 30)
                )
                if len(faces) > 0:
                    return list(faces)
            except Exception:
                pass

        # DeepFace ile yüz çıkarma denemesi
        try:
            from deepface import DeepFace
            extracted = DeepFace.extract_faces(frame, detector_backend="opencv", enforce_detection=False)
            results = []
            for item in extracted:
                area = item.get("facial_area", {})
                x, y, w, h = area.get("x", 0), area.get("y", 0), area.get("w", 0), area.get("h", 0)
                if w > 20 and h > 20:
                    results.append((int(x), int(y), int(w), int(h)))
            if results:
                return results
        except Exception:
            pass

        # Fallback: Karenin merkezini odak yüz olarak öner
        fh, fw, _ = frame.shape
        return [(int(fw * 0.25), int(fh * 0.15), int(fw * 0.5), int(fh * 0.6))]

    def save_face_crop(self, frame: np.ndarray, bbox: Tuple[int, int, int, int], char_name: str) -> Path:
        """Tespit edilen yüzü biraz pay (margin) ekleyerek kırpar ve karakter klasörüne kaydeder."""
        char_dir = self.characters_base_dir / char_name
        char_dir.mkdir(parents=True, exist_ok=True)

        h, w, _ = frame.shape
        x, y, fw, fh = bbox

        # Yüzün çevresinden %20 pay bırak
        margin_x = int(fw * 0.2)
        margin_y = int(fh * 0.2)

        x1 = max(0, x - margin_x)
        y1 = max(0, y - margin_y)
        x2 = min(w, x + fw + margin_x)
        y2 = min(h, y + fh + margin_y)

        crop = frame[y1:y2, x1:x2]

        # Benzersiz isimle kaydet
        existing = len(list(char_dir.glob("ref_video_*.jpg")))
        save_path = char_dir / f"ref_video_{existing + 1}.jpg"
        cv2.imwrite(str(save_path), crop)
        return save_path

    def pick_from_timestamp(self, video_path: Path, timestamp_sec: float, char_name: str) -> Optional[Path]:
        """
        Belirtilen saniyedeki (örn: 125.0 sn veya '02:05') kareyi açar,
        yüzü otomatik bulur ve referans olarak kaydeder.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            console.print(f"[red]Video açılamadı: {video_path}[/red]")
            return None

        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000.0)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            console.print(f"[red]{timestamp_sec:.1f}. saniyeden kare alınamadı![/red]")
            return None

        faces = self.detect_faces_in_frame(frame)
        if not faces:
            console.print(f"[yellow]{timestamp_sec:.1f}. saniyede otomatik yüz bulunamadı, tüm kare kaydediliyor.[/yellow]")
            char_dir = self.characters_base_dir / char_name
            char_dir.mkdir(parents=True, exist_ok=True)
            save_path = char_dir / f"ref_video_{int(timestamp_sec)}s.jpg"
            cv2.imwrite(str(save_path), frame)
            return save_path

        # En büyük yüzü karakter kabul et
        faces = sorted(faces, key=lambda b: b[2] * b[3], reverse=True)
        saved = self.save_face_crop(frame, faces[0], char_name)
        console.print(f"[bold green]✔ '{char_name}' için referans yüz kaydedildi:[/bold green] {saved.name}")
        return saved

    def interactive_gui_picker(self, video_path: Path) -> Dict[str, List[Path]]:
        """
        OpenCV penceresi açarak kullanıcının klavye tuşlarıyla videoyu sarmasını,
        yüzü görüp tek tuşla etiketlemesini sağlar.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            console.print(f"[red]Video açılamadı: {video_path}[/red]")
            return {}

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps

        console.print("\n[bold cyan]=== GÖRSEL KARAKTER SEÇİCİ AÇILDI ===[/bold cyan]")
        console.print("[yellow]KONTROLLER:[/yellow]")
        console.print("  [D] / [Sağ Ok] : 5 sn İleri")
        console.print("  [A] / [Sol Ok] : 5 sn Geri")
        console.print("  [W]            : 30 sn İleri")
        console.print("  [S]            : 30 sn Geri")
        console.print("  [BOŞLUK]       : Kareyi dondur ve Yüzleri Numaralandır")
        console.print("  [1..9]         : Numaralandırılan Yüzü Seç ve Karakter Adı Ver")
        console.print("  [ENTER / Q]    : Seçimi Bitir ve Taramayı Başlat\n")

        curr_frame_idx = 0
        frozen_mode = False
        detected_faces: List[Tuple[int, int, int, int]] = []
        last_frame: Optional[np.ndarray] = None
        saved_chars: Dict[str, List[Path]] = {}

        window_name = "AI Scenepack - Karakter Secici (Q: Cikis/Baslat, BOSLUK: Yuz Bul)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, 960, 540)

        while True:
            if not frozen_mode:
                cap.set(cv2.CAP_PROP_POS_FRAMES, curr_frame_idx)
                ret, frame = cap.read()
                if not ret or frame is None:
                    curr_frame_idx = max(0, curr_frame_idx - 1)
                    continue

                last_frame = frame.copy()
                curr_sec = curr_frame_idx / fps

                display = frame.copy()
                info_text = f"Zaman: {int(curr_sec//60):02d}:{int(curr_sec%60):02d} / {int(duration//60):02d}:{int(duration%60):02d} | BOSLUK: Yuz Tara"
                cv2.putText(display, info_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            else:
                display = last_frame.copy()
                for idx, (x, y, w, h) in enumerate(detected_faces, start=1):
                    cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    label = f"[{idx}] YUZ"
                    cv2.putText(display, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                prompt_text = "Secmek istediginiz yuz numarasina basin (1-9). Devam icin BOSLUK."
                cv2.putText(display, prompt_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)

            cv2.imshow(window_name, display)
            key = cv2.waitKey(30) & 0xFF

            if key in (ord('q'), ord('Q'), 13, 27):  # Q, ENTER veya ESC
                break

            elif key == ord(' ') and not frozen_mode:
                # Karedeki yüzleri tespit et ve dondur
                if last_frame is not None:
                    detected_faces = self.detect_faces_in_frame(last_frame)
                    if detected_faces:
                        frozen_mode = True
                    else:
                        console.print("[yellow]Bu karede belirgin yüz bulunamadı, biraz ilerleyin.[/yellow]")

            elif key == ord(' ') and frozen_mode:
                # Normal oynatmaya geri dön
                frozen_mode = False
                detected_faces = []

            # 1-9 arası tuşla yüz seçimi
            elif frozen_mode and ord('1') <= key <= ord('9'):
                face_idx = key - ord('1')
                if face_idx < len(detected_faces) and last_frame is not None:
                    target_bbox = detected_faces[face_idx]
                    
                    # Terminalden karakter ismini al
                    console.print(f"\n[green]{face_idx + 1}. Yüz Seçildi![/green]")
                    char_name = Prompt.ask("Bu karakterin adı nedir?", default="Polat").strip()

                    saved_path = self.save_face_crop(last_frame, target_bbox, char_name)
                    if char_name not in saved_chars:
                        saved_chars[char_name] = []
                    saved_chars[char_name].append(saved_path)

                    console.print(f"[bold green]✔ '{char_name}' kaydedildi:[/bold green] {saved_path.name}")
                    frozen_mode = False
                    detected_faces = []

            elif not frozen_mode:
                # Navigasyon tuşları
                if key in (ord('d'), ord('D'), 83):  # 5 sn ileri
                    curr_frame_idx = min(total_frames - 1, curr_frame_idx + int(fps * 5))
                elif key in (ord('a'), ord('A'), 81):  # 5 sn geri
                    curr_frame_idx = max(0, curr_frame_idx - int(fps * 5))
                elif key in (ord('w'), ord('W')):  # 30 sn ileri
                    curr_frame_idx = min(total_frames - 1, curr_frame_idx + int(fps * 30))
                elif key in (ord('s'), ord('S')):  # 30 sn geri
                    curr_frame_idx = max(0, curr_frame_idx - int(fps * 30))

        cap.release()
        cv2.destroyAllWindows()
        return saved_chars
