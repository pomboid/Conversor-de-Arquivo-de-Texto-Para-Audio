import os
import tempfile
import asyncio
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import fitz  # PyMuPDF
import docx  # python-docx
import edge_tts
from pydub import AudioSegment
import pygame

# === Funções de Extração de Texto ===
def extract_text(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    text = ""
    if ext == ".pdf":
        doc = fitz.open(filepath)
        for page in doc:
            text += page.get_text()
    elif ext == ".txt":
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    elif ext == ".docx":
        doc = docx.Document(filepath)
        for para in doc.paragraphs:
            text += para.text + "\n"
    else:
        raise ValueError("Tipo de arquivo não suportado. Use PDF, TXT ou DOCX.")
    return text

# === Funções de TTS ===
async def list_voices():
    voices = await edge_tts.VoicesManager.create()
    ptb_voices = [v for v in voices.voices if "pt-BR" in v["Locale"]]
    return ptb_voices

async def preview_voice(voice_name):
    # Texto de prévia normal
    preview_text = "Olá, esta é uma prévia da voz."
    # Texto maior para vozes problemáticas
    if voice_name in ["pt-BR-Marcerio:DragonHDLatestNeural", "pt-BR-Thalita:DragonHDLatestNeural"]:
        preview_text = (
            "Olá! Esta é uma prévia da voz selecionada. "
            "Este texto é um pouco maior para garantir que o áudio seja gerado corretamente."
        )
    try:
        tmp_mp3 = tempfile.mktemp(suffix=".mp3")
        communicate = edge_tts.Communicate(preview_text, voice_name)
        await communicate.save(tmp_mp3)

        # Inicializa pygame e toca o áudio
        pygame.mixer.init()
        pygame.mixer.music.load(tmp_mp3)
        pygame.mixer.music.play()

        # Espera o áudio terminar sem travar o GUI
        while pygame.mixer.music.get_busy():
            await asyncio.sleep(0.1)

        pygame.mixer.quit()
        os.remove(tmp_mp3)
    except edge_tts.exceptions.NoAudioReceived:
        messagebox.showerror("Erro", f"Não foi possível gerar áudio para a voz '{voice_name}'.")

async def generate_audio(text, voice_name, output_path, speed=1.4):
    tmp_mp3 = tempfile.mktemp(suffix=".mp3")
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(tmp_mp3)

    sound = AudioSegment.from_file(tmp_mp3)
    faster_sound = sound._spawn(sound.raw_data, overrides={"frame_rate": int(sound.frame_rate * speed)})
    faster_sound = faster_sound.set_frame_rate(sound.frame_rate)
    faster_sound.export(output_path, format="mp3")
    os.remove(tmp_mp3)

# === Dividir por Capítulos ===
def split_by_chapters(text):
    import re
    chapters = re.split(r'(Cap[ií]tulo .*?\n)', text)
    result = []
    if len(chapters) == 1:
        return [("Texto Completo", text)]
    for i in range(1, len(chapters), 2):
        title = chapters[i].strip()
        content = chapters[i+1] if i+1 < len(chapters) else ""
        result.append((title, content))
    return result

# === Classe da GUI ===
class TextToAudioGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Transformar Texto em Áudio")
        self.root.geometry("700x600")
        self.root.resizable(True, True)
        self.selected_voice = None
        self.text = None
        self.audio_done = False

        # Arquivo
        tk.Label(root, text="Arquivo:").pack(anchor="w", padx=10, pady=(10,0))
        self.file_frame = tk.Frame(root)
        self.file_frame.pack(fill="x", padx=10)
        self.file_entry = tk.Entry(self.file_frame)
        self.file_entry.pack(side="left", fill="x", expand=True)
        tk.Button(self.file_frame, text="Selecionar", command=self.select_file).pack(side="left", padx=5)

        # Vozes
        tk.Label(root, text="Vozes disponíveis:").pack(anchor="w", padx=10, pady=(10,0))
        self.voice_frame = tk.Frame(root)
        self.voice_frame.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self.voice_canvas = tk.Canvas(self.voice_frame)
        self.voice_scroll = ttk.Scrollbar(self.voice_frame, orient="vertical", command=self.voice_canvas.yview)
        self.voice_inner = tk.Frame(self.voice_canvas)
        self.voice_inner.bind(
            "<Configure>",
            lambda e: self.voice_canvas.configure(scrollregion=self.voice_canvas.bbox("all"))
        )
        self.voice_canvas.create_window((0,0), window=self.voice_inner, anchor="nw")
        self.voice_canvas.configure(yscrollcommand=self.voice_scroll.set)
        self.voice_canvas.pack(side="left", fill="both", expand=True)
        self.voice_scroll.pack(side="right", fill="y")

        # Scroll do mouse
        def _on_mousewheel(event):
            self.voice_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.voice_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Velocidade
        tk.Label(root, text="Velocidade:").pack(anchor="w", padx=10)
        self.speed_var = tk.StringVar(value="1.4")
        self.speed_dropdown = ttk.Combobox(
            root,
            textvariable=self.speed_var,
            values=[str(round(x*0.1,1)) for x in range(10,21)],
            state="readonly"  # Apenas seleção
        )
        self.speed_dropdown.pack(fill="x", padx=10)

        # Dividir capítulos
        self.chapter_var = tk.BooleanVar()
        tk.Checkbutton(root, text="Dividir por capítulos", variable=self.chapter_var).pack(anchor="w", padx=10, pady=(5,10))

        # Gerar áudio
        self.generate_btn = tk.Button(root, text="🎧 Gerar Áudio", command=self.start_generate)
        self.generate_btn.pack(pady=5)

        # Barra de progresso
        self.progress = ttk.Progressbar(root, orient="horizontal", length=600, mode="determinate")
        self.progress.pack(pady=10, padx=10)

        # Inicializar vozes
        self.root.after(100, self.load_voices)

    def select_file(self):
        filepath = filedialog.askopenfilename(
            title="Selecione o arquivo",
            filetypes=[("Arquivos de texto","*.pdf *.txt *.docx"), ("Todos","*.*")]
        )
        if filepath:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, filepath)
            self.text = extract_text(filepath)

    def load_voices(self):
        async def load():
            self.voices = await list_voices()
            for v in self.voices:
                frame = tk.Frame(self.voice_inner)
                frame.pack(fill="x", pady=2)
                tk.Label(frame, text=f"{v['ShortName']} ({v['VoiceType']})").pack(side="left", padx=5)
                tk.Button(
                    frame, text="▶️",
                    command=lambda voice=v: threading.Thread(target=lambda: asyncio.run(preview_voice(voice["ShortName"])), daemon=True).start()
                ).pack(side="left", padx=5)
                tk.Button(frame, text="Selecionar", command=lambda voice=v: self.select_voice(voice)).pack(side="left", padx=5)
        threading.Thread(target=lambda: asyncio.run(load()), daemon=True).start()

    def select_voice(self, voice):
        self.selected_voice = voice['ShortName']
        messagebox.showinfo("Selecionada", f"Voz {voice['ShortName']} selecionada!")

    def start_generate(self):
        if not self.text or not self.selected_voice:
            messagebox.showwarning("Erro", "Selecione arquivo e voz primeiro!")
            return

        speed = float(self.speed_var.get())
        divide_chapters = self.chapter_var.get()
        out_name = os.path.splitext(os.path.basename(self.file_entry.get()))[0] + f"_output_{speed}x.mp3"

        threading.Thread(
            target=self.generate_audio_thread,
            args=(self.text, self.selected_voice, out_name, speed, divide_chapters),
            daemon=True
        ).start()

    def generate_audio_thread(self, text, voice, output_path, speed, divide_chapters):
        self.progress['value'] = 0
        self.progress.update()
        self.audio_done = False

        # Simula progresso
        def progress_sim():
            while not self.audio_done:
                self.progress['value'] += 1
                if self.progress['value'] > 99:
                    self.progress['value'] = 99
                self.progress.update()
                time.sleep(0.05)
            self.progress['value'] = 100
            self.progress.update()

        threading.Thread(target=progress_sim, daemon=True).start()

        # Geração real
        if divide_chapters:
            chapters = split_by_chapters(text)
            full_text = ""
            for title, content in chapters:
                full_text += content + "\n"
            asyncio.run(generate_audio(full_text, voice, output_path, speed))
        else:
            asyncio.run(generate_audio(text, voice, output_path, speed))

        self.audio_done = True
        messagebox.showinfo("Pronto!", f"Áudio gerado: {output_path}")

# === Rodar GUI ===
if __name__ == "__main__":
    root = tk.Tk()
    app = TextToAudioGUI(root)
    root.mainloop()
