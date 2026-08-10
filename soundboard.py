#!/usr/bin/env python3
"""
SoundBoard — случайное воспроизведение звуков с настраиваемой вероятностью.

Запустите этот скрипт в папке со звуковыми файлами.
Он автоматически найдёт все поддерживаемые форматы и покажет их в интерфейсе.

Зависимости: pygame
Установка:  pip install pygame
"""

import os
import sys
import random
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
except pygame.error:
    PYGAME_AVAILABLE = False

# ─── Поддерживаемые расширения ───────────────────────────────────────────────
SOUND_EXTENSIONS = {
    ".mp3", ".wav", ".ogg", ".flac", ".mid", ".midi",
    ".opus", ".aiff", ".aif", ".wma", ".m4a",
}

# ─── Цветовая палитра (тёмная тема) ─────────────────────────────────────────
COLORS = {
    "bg":           "#1e1e2e",
    "bg_secondary": "#2a2a3c",
    "bg_tertiary":  "#333347",
    "fg":           "#cdd6f4",
    "fg_dim":       "#7f849c",
    "accent":       "#89b4fa",
    "accent_hover": "#74c7ec",
    "green":        "#a6e3a1",
    "red":          "#f38ba8",
    "yellow":       "#f9e2af",
    "border":       "#45475a",
    "entry_bg":     "#313244",
    "scrollbar":    "#585b70",
}


class SoundItem:
    """Модель одного звукового файла."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.enabled = tk.BooleanVar(value=True)
        self.volume = tk.DoubleVar(value=0.80)  # 0.0 – 1.0
        self.play_count = 0


class SoundBoardApp:
    """Главное приложение SoundBoard."""

    TICK_MS = 100  # интервал опроса GUI-цикла (мс)

    def __init__(self, root: tk.Tk, sound_dir: str | None = None):
        self.root = root
        self.root.title("🎵 SoundBoard")
        self.root.configure(bg=COLORS["bg"])
        self.root.minsize(520, 420)
        self.root.resizable(True, True)

        # По умолчанию ищем в папке, из которой запустили программу. Это
        # соответствует команде из README: `cd /папка/со/звуками` → запуск.
        # Раньше здесь использовалась папка самого скрипта, поэтому при запуске
        # `python /путь/к/soundboard.py` файлы из текущей папки игнорировались.
        self.sound_dir = Path(sound_dir).expanduser().resolve() if sound_dir else Path.cwd().resolve()

        # Глобальные переменные
        self.prob_num = tk.IntVar(value=1)
        self.prob_den = tk.IntVar(value=100_000)
        self.global_volume = tk.DoubleVar(value=0.80)
        self.check_interval = tk.DoubleVar(value=1.0)  # секунды
        self.running = False
        self.total_checks = 0
        self.total_plays = 0
        self.last_played = ""

        # Звуковые файлы
        self.sounds: list[SoundItem] = []
        self.sound_rows: dict[str, dict] = {}  # filename → виджеты строки

        # Стиль
        self._setup_styles()

        # Построение интерфейса
        self._build_ui()

        # Загрузка звуков
        self._scan_sounds()

        # Центрирование окна
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

        # Закрытие
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── Стили ttk ───────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")

        s.configure("TFrame", background=COLORS["bg"])
        s.configure("Secondary.TFrame", background=COLORS["bg_secondary"])
        s.configure("TLabel", background=COLORS["bg"], foreground=COLORS["fg"],
                     font=("Segoe UI", 10))
        s.configure("Dim.TLabel", background=COLORS["bg"], foreground=COLORS["fg_dim"],
                     font=("Segoe UI", 9))
        s.configure("Header.TLabel", background=COLORS["bg"], foreground=COLORS["accent"],
                     font=("Segoe UI", 14, "bold"))
        s.configure("Stat.TLabel", background=COLORS["bg_secondary"],
                     foreground=COLORS["fg"], font=("Segoe UI", 9))
        s.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["fg"],
                     font=("Segoe UI", 10), selectcolor=COLORS["entry_bg"],
                     activebackground=COLORS["bg"], activeforeground=COLORS["fg"])
        s.configure("Secondary.TCheckbutton", background=COLORS["bg_secondary"],
                     foreground=COLORS["fg"], font=("Segoe UI", 10),
                     selectcolor=COLORS["entry_bg"],
                     activebackground=COLORS["bg_secondary"],
                     activeforeground=COLORS["fg"])
        s.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        s.configure("Start.TButton", foreground=COLORS["green"])
        s.configure("Stop.TButton", foreground=COLORS["red"])

        s.configure("TScale", background=COLORS["bg"], troughcolor=COLORS["entry_bg"])

        s.configure("TEntry", fieldbackground=COLORS["entry_bg"],
                     foreground=COLORS["fg"], insertcolor=COLORS["fg"])

        s.configure("Vertical.TScrollbar", background=COLORS["scrollbar"],
                     troughcolor=COLORS["bg_secondary"], borderwidth=0,
                     arrowsize=14)

    # ─── Построение UI ───────────────────────────────────────────────────────
    def _build_ui(self):
        # ─ Заголовок ─
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=14, pady=(12, 4))
        ttk.Label(header, text="🎵 SoundBoard", style="Header.TLabel").pack(side="left")
        self.dir_label = ttk.Label(header, text="", style="Dim.TLabel")
        self.dir_label.pack(side="right")

        # ─ Панель управления (верхняя) ─
        ctrl = ttk.Frame(self.root, style="Secondary.TFrame")
        ctrl.pack(fill="x", padx=14, pady=4)
        ctrl.columnconfigure(1, weight=1)

        # Вероятность
        row_prob = ttk.Frame(ctrl, style="Secondary.TFrame")
        row_prob.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 2))

        ttk.Label(row_prob, text="Вероятность:", style="Stat.TLabel").pack(side="left")
        self.prob_num_entry = tk.Entry(
            row_prob, textvariable=self.prob_num, width=7,
            bg=COLORS["entry_bg"], fg=COLORS["fg"], insertbackground=COLORS["fg"],
            font=("Segoe UI", 10), relief="flat", bd=2,
        )
        self.prob_num_entry.pack(side="left", padx=(6, 2))
        ttk.Label(row_prob, text="/", style="Stat.TLabel").pack(side="left")
        self.prob_den_entry = tk.Entry(
            row_prob, textvariable=self.prob_den, width=10,
            bg=COLORS["entry_bg"], fg=COLORS["fg"], insertbackground=COLORS["fg"],
            font=("Segoe UI", 10), relief="flat", bd=2,
        )
        self.prob_den_entry.pack(side="left", padx=(2, 6))
        self.prob_pct_label = ttk.Label(row_prob, text="(0.001%)", style="Dim.TLabel")
        self.prob_pct_label.pack(side="left", padx=4)
        self.prob_num.trace_add("write", self._update_prob_label)
        self.prob_den.trace_add("write", self._update_prob_label)

        # Громкость (глобальная)
        row_vol = ttk.Frame(ctrl, style="Secondary.TFrame")
        row_vol.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=2)

        ttk.Label(row_vol, text="Громкость:", style="Stat.TLabel").pack(side="left")
        self.vol_scale = tk.Scale(
            row_vol, from_=0, to=100, orient="horizontal",
            variable=tk.IntVar(value=80), length=200, showvalue=False,
            bg=COLORS["bg_secondary"], fg=COLORS["fg"],
            troughcolor=COLORS["entry_bg"], highlightthickness=0,
            sliderrelief="flat", bd=0, sliderlength=18,
            command=self._on_global_volume_change,
        )
        self.vol_scale.pack(side="left", padx=(6, 2), fill="x", expand=True)
        self.vol_label = ttk.Label(row_vol, text="80%", style="Stat.TLabel", width=5)
        self.vol_label.pack(side="left")
        self.global_volume.set(0.80)

        # Интервал проверки
        row_int = ttk.Frame(ctrl, style="Secondary.TFrame")
        row_int.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=2)

        ttk.Label(row_int, text="Интервал (сек):", style="Stat.TLabel").pack(side="left")
        self.interval_entry = tk.Entry(
            row_int, textvariable=self.check_interval, width=6,
            bg=COLORS["entry_bg"], fg=COLORS["fg"], insertbackground=COLORS["fg"],
            font=("Segoe UI", 10), relief="flat", bd=2,
        )
        self.interval_entry.pack(side="left", padx=(6, 0))

        # Кнопки + статистика
        row_btn = ttk.Frame(ctrl, style="Secondary.TFrame")
        row_btn.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(6, 8))

        self.start_btn = tk.Button(
            row_btn, text="▶ Запустить", width=14,
            font=("Segoe UI", 10, "bold"), fg=COLORS["green"],
            bg=COLORS["bg_tertiary"], activebackground=COLORS["bg_tertiary"],
            activeforeground=COLORS["green"], relief="flat", bd=0, cursor="hand2",
            command=self._toggle_running,
        )
        self.start_btn.pack(side="left", padx=(0, 6))

        self.test_btn = tk.Button(
            row_btn, text="🔊 Тест", width=10,
            font=("Segoe UI", 10, "bold"), fg=COLORS["yellow"],
            bg=COLORS["bg_tertiary"], activebackground=COLORS["bg_tertiary"],
            activeforeground=COLORS["yellow"], relief="flat", bd=0, cursor="hand2",
            command=self._test_play,
        )
        self.test_btn.pack(side="left", padx=(0, 6))

        self.rescan_btn = tk.Button(
            row_btn, text="🔄 Обновить", width=10,
            font=("Segoe UI", 10), fg=COLORS["fg_dim"],
            bg=COLORS["bg_tertiary"], activebackground=COLORS["bg_tertiary"],
            activeforeground=COLORS["fg"], relief="flat", bd=0, cursor="hand2",
            command=self._scan_sounds,
        )
        self.rescan_btn.pack(side="left", padx=(0, 6))

        # Включить/выключить все
        self.toggle_all_btn = tk.Button(
            row_btn, text="☑ Все", width=7,
            font=("Segoe UI", 9), fg=COLORS["fg_dim"],
            bg=COLORS["bg_tertiary"], activebackground=COLORS["bg_tertiary"],
            activeforeground=COLORS["fg"], relief="flat", bd=0, cursor="hand2",
            command=self._enable_all,
        )
        self.toggle_all_btn.pack(side="left", padx=(0, 3))

        self.toggle_none_btn = tk.Button(
            row_btn, text="☐ Никакие", width=9,
            font=("Segoe UI", 9), fg=COLORS["fg_dim"],
            bg=COLORS["bg_tertiary"], activebackground=COLORS["bg_tertiary"],
            activeforeground=COLORS["fg"], relief="flat", bd=0, cursor="hand2",
            command=self._disable_all,
        )
        self.toggle_none_btn.pack(side="left")

        # Статистика
        stat_frame = ttk.Frame(row_btn, style="Secondary.TFrame")
        stat_frame.pack(side="right")
        self.stat_label = ttk.Label(stat_frame, text="Проверок: 0 | Воспроизведено: 0",
                                     style="Dim.TLabel")
        self.stat_label.pack(side="right")

        # ─ Разделитель ─
        sep = tk.Frame(self.root, bg=COLORS["border"], height=1)
        sep.pack(fill="x", padx=14, pady=(4, 2))

        # ─ Заголовок списка ─
        list_header = ttk.Frame(self.root)
        list_header.pack(fill="x", padx=14, pady=(2, 0))
        self.count_label = ttk.Label(list_header, text="Звуки: 0", style="Dim.TLabel")
        self.count_label.pack(side="left")

        # ─ Список звуков (с прокруткой) ─
        list_outer = ttk.Frame(self.root, style="Secondary.TFrame")
        list_outer.pack(fill="both", expand=True, padx=14, pady=(2, 12))

        self.canvas = tk.Canvas(list_outer, bg=COLORS["bg_secondary"],
                                highlightthickness=0, bd=0)
        self.v_scroll = ttk.Scrollbar(list_outer, orient="vertical",
                                       command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set)

        self.v_scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scroll_frame = ttk.Frame(self.canvas, style="Secondary.TFrame")
        self.scroll_window = self.canvas.create_window(
            (0, 0), window=self.scroll_frame, anchor="nw"
        )
        self.scroll_frame.bind("<Configure>",
                                lambda e: self.canvas.configure(
                                    scrollregion=self.canvas.bbox("all")
                                ))
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Прокрутка колёсиком
        self.root.bind("<MouseWheel>", self._on_mousewheel)
        self.root.bind("<Button-4>", self._on_mousewheel_linux)
        self.root.bind("<Button-5>", self._on_mousewheel_linux)

        # ─ Строка статуса внизу ─
        self.status_var = tk.StringVar(value="Готов")
        status_bar = tk.Label(
            self.root, textvariable=self.status_var, anchor="w",
            bg=COLORS["bg_tertiary"], fg=COLORS["fg_dim"],
            font=("Segoe UI", 9), padx=10, pady=3,
        )
        status_bar.pack(fill="x", side="bottom")

        # Запуск периодической проверки
        self._last_tick = time.monotonic()
        self._schedule_tick()

    # ─── Сканирование звуков ─────────────────────────────────────────────────
    def _scan_sounds(self):
        # Удаляем старые строки
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        self.sounds.clear()
        self.sound_rows.clear()

        # Показываем путь даже если в нём не оказалось подходящих файлов.
        self.dir_label.configure(text=str(self.sound_dir))

        # Поиск файлов в самой папке (подпапки намеренно не сканируются).
        # Не прерываем интерфейс, если папка стала недоступна после запуска.
        found: list[Path] = []
        try:
            for p in sorted(self.sound_dir.iterdir()):
                if p.is_file() and p.suffix.lower() in SOUND_EXTENSIONS:
                    found.append(p)
        except OSError as exc:
            self.count_label.configure(text="Звуки: 0")
            self.status_var.set(f"⚠ Не удалось открыть папку: {exc}")
            return

        if not found:
            no_lbl = ttk.Label(
                self.scroll_frame,
                text=f"  Звуковые файлы не найдены в:\n  {self.sound_dir}\n\n"
                     f"  Поддерживаемые форматы:\n  {', '.join(sorted(SOUND_EXTENSIONS))}",
                style="Dim.TLabel",
            )
            no_lbl.pack(anchor="w", padx=12, pady=20)
            self.count_label.configure(text="Звуки: 0")
            self.status_var.set("Звуки не найдены")
            return

        for fpath in found:
            item = SoundItem(str(fpath))
            self.sounds.append(item)
            self._add_sound_row(item, len(self.sounds) - 1)

        self.count_label.configure(text=f"Звуки: {len(self.sounds)}")
        self.status_var.set(f"Загружено {len(self.sounds)} звуков")

    def _add_sound_row(self, item: SoundItem, idx: int):
        row = ttk.Frame(self.scroll_frame, style="Secondary.TFrame")
        row.pack(fill="x", padx=4, pady=1)

        # Чекбокс
        cb = tk.Checkbutton(
            row, variable=item.enabled,
            bg=COLORS["bg_secondary"], fg=COLORS["fg"],
            selectcolor=COLORS["entry_bg"], activebackground=COLORS["bg_secondary"],
            activeforeground=COLORS["fg"], cursor="hand2",
        )
        cb.pack(side="left", padx=(6, 2))

        # Номер
        num_lbl = ttk.Label(row, text=f"{idx+1:3d}", style="Dim.TLabel", width=4)
        num_lbl.pack(side="left")

        # Имя файла
        name_lbl = ttk.Label(row, text=item.filename, style="Stat.TLabel", width=35,
                              anchor="w")
        name_lbl.pack(side="left", padx=(0, 6), fill="x", expand=True)

        # Счётчик воспроизведений
        count_lbl = ttk.Label(row, text="×0", style="Dim.TLabel", width=5)
        count_lbl.pack(side="right", padx=(2, 6))

        # Громкость звука (мини-слайдер)
        vol_var = tk.IntVar(value=int(item.volume.get() * 100))
        vol_scale = tk.Scale(
            row, from_=0, to=100, orient="horizontal",
            variable=vol_var, length=90, showvalue=False,
            bg=COLORS["bg_secondary"], fg=COLORS["fg"],
            troughcolor=COLORS["entry_bg"], highlightthickness=0,
            sliderrelief="flat", bd=0, sliderlength=12,
            command=lambda v, it=item, vv=vol_var: it.volume.set(int(v) / 100),
        )
        vol_scale.pack(side="right", padx=(0, 2))

        vol_lbl = ttk.Label(row, text="80%", style="Dim.TLabel", width=5)
        vol_lbl.pack(side="right", padx=(0, 2))

        # Обновление метки громкости
        def _update_vol_label(*_):
            vol_lbl.configure(text=f"{vol_var.get()}%")
        vol_var.trace_add("write", _update_vol_label)

        # Кнопка тестового воспроизведения одного звука
        test_btn = tk.Button(
            row, text="▶", width=2,
            font=("Segoe UI", 8), fg=COLORS["accent"],
            bg=COLORS["bg_tertiary"], activebackground=COLORS["bg_tertiary"],
            activeforeground=COLORS["accent_hover"], relief="flat", bd=0, cursor="hand2",
            command=lambda it=item: self._play_sound(it),
        )
        test_btn.pack(side="right", padx=(2, 0))

        self.sound_rows[item.filename] = {
            "row": row, "count_lbl": count_lbl, "vol_var": vol_var,
        }

    # ─── Воспроизведение ─────────────────────────────────────────────────────
    def _play_sound(self, item: SoundItem):
        if not PYGAME_AVAILABLE:
            self.status_var.set("⚠ pygame не установлен — pip install pygame")
            return
        try:
            snd = pygame.mixer.Sound(item.filepath)
            vol = item.volume.get() * self.global_volume.get()
            snd.set_volume(max(0.0, min(1.0, vol)))
            snd.play()
            item.play_count += 1
            self.total_plays += 1
            self.last_played = item.filename
            # Обновить счётчик в строке
            if item.filename in self.sound_rows:
                self.sound_rows[item.filename]["count_lbl"].configure(
                    text=f"×{item.play_count}"
                )
            self.status_var.set(f"🔊 {item.filename}")
        except Exception as e:
            self.status_var.set(f"⚠ Ошибка: {e}")

    def _pick_and_play(self):
        """Выбрать случайный включённый звук и воспроизвести."""
        enabled = [s for s in self.sounds if s.enabled.get()]
        if not enabled:
            self.status_var.set("Нет включённых звуков")
            return
        chosen = random.choice(enabled)
        self._play_sound(chosen)

    # ─── Главный цикл (тикер) ────────────────────────────────────────────────
    def _schedule_tick(self):
        self.root.after(self.TICK_MS, self._tick)

    def _tick(self):
        if self.running:
            now = time.monotonic()
            interval = max(0.1, self.check_interval.get())
            if now - self._last_tick >= interval:
                self._last_tick = now
                self.total_checks += 1

                # Вычисляем вероятность
                try:
                    num = max(1, self.prob_num.get())
                    den = max(1, self.prob_den.get())
                except (tk.TclError, ValueError):
                    num, den = 1, 100_000

                if random.randint(1, den) <= num:
                    self._pick_and_play()

                # Обновить статистику
                self.stat_label.configure(
                    text=f"Проверок: {self.total_checks} | Воспроизведено: {self.total_plays}"
                )

        self._schedule_tick()

    # ─── Управление запуском ─────────────────────────────────────────────────
    def _toggle_running(self):
        if self.running:
            self.running = False
            self.start_btn.configure(text="▶ Запустить", fg=COLORS["green"])
            self.status_var.set("Остановлено")
        else:
            if not self.sounds:
                self.status_var.set("⚠ Нет звуков для воспроизведения")
                return
            self.running = True
            self._last_tick = time.monotonic()
            self.start_btn.configure(text="⏹ Остановить", fg=COLORS["red"])
            self.status_var.set("Работает…")

    def _test_play(self):
        """Тестовое воспроизведение — всегда играет случайный звук."""
        self._pick_and_play()

    # ─── Включить / выключить все ────────────────────────────────────────────
    def _enable_all(self):
        for s in self.sounds:
            s.enabled.set(True)

    def _disable_all(self):
        for s in self.sounds:
            s.enabled.set(False)

    # ─── Обработчики UI ──────────────────────────────────────────────────────
    def _on_global_volume_change(self, val):
        v = int(float(val))
        self.global_volume.set(v / 100)
        self.vol_label.configure(text=f"{v}%")

    def _update_prob_label(self, *_):
        try:
            n = self.prob_num.get()
            d = self.prob_den.get()
            if d > 0:
                pct = (n / d) * 100
                if pct < 0.001:
                    self.prob_pct_label.configure(text=f"({pct:.6f}%)")
                elif pct < 1:
                    self.prob_pct_label.configure(text=f"({pct:.4f}%)")
                else:
                    self.prob_pct_label.configure(text=f"({pct:.2f}%)")
            else:
                self.prob_pct_label.configure(text="")
        except (tk.TclError, ValueError):
            self.prob_pct_label.configure(text="")

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.scroll_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

    def _on_close(self):
        self.running = False
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
        self.root.destroy()


# ─── Точка входа ─────────────────────────────────────────────────────────────
def main():
    if not PYGAME_AVAILABLE:
        print("⚠ pygame не найден. Установите: pip install pygame")
        print("  Запускаю интерфейс без воспроизведения…")

    root = tk.Tk()

    # Можно передать папку через аргумент командной строки
    sound_dir = None
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1])
        if candidate.is_dir():
            sound_dir = str(candidate)
        else:
            print(f"⚠ Папка не найдена: {sys.argv[1]}, используем текущую")

    app = SoundBoardApp(root, sound_dir)
    root.mainloop()


if __name__ == "__main__":
    main()
