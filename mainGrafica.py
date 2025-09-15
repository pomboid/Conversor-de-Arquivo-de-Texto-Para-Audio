import os
import tempfile
import asyncio
import threading
import time
import re
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
    return text.strip()

# === Funções de TTS ===
async def list_voices():
    voices = await edge_tts.VoicesManager.create()
    ptb_voices = [v for v in voices.voices if "pt-BR" in v["Locale"]]
    return ptb_voices

async def preview_voice(voice_name):
    text = "Olá, esta é uma prévia da voz."
    await generate_audio_single(text, voice_name, None, speed=1.0, play_preview=True)

async def generate_audio_single(text, voice_name, output_path, speed=1.4, play_preview=False):
    """
    Gera áudio de um bloco de texto.
    Se play_preview=True, apenas reproduz o áudio sem salvar.
    """
    tmp_mp3 = tempfile.mktemp(suffix=".mp3")
    try:
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(tmp_mp3)
        sound = AudioSegment.from_file(tmp_mp3)
        sound = sound._spawn(sound.raw_data, overrides={"frame_rate": int(sound.frame_rate * speed)})
        sound = sound.set_frame_rate(sound.frame_rate)
        if play_preview:
            pygame.mixer.init()
            pygame.mixer.music.load(tmp_mp3)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
            pygame.mixer.quit()
        elif output_path:
            sound.export(output_path, format="mp3")
    finally:
        if os.path.exists(tmp_mp3):
            os.remove(tmp_mp3)

async def generate_audio(text, voice_name, output_path, speed=1.4):
    """
    Divide o texto em frases e gera áudio concatenado, respeitando pausas naturais.
    """
    # Remove quebras de linha extras
    text = text.replace("\n", " ").strip()
    # Divide em frases por pontuação
    phrases = re.split(r'([.!?])', text)
    phrases = [phrases[i]+phrases[i+1] for i in range(0, len(phrases)-1, 2)]
    
    combined = AudioSegment.silent(duration=0)
    for phrase in phrases:
        clean_phrase = phrase.strip()
        if not clean_phrase:
            continue
        tmp_file = tempfile.mktemp(suffix=".mp3")
        await generate_audio_single(clean_phrase, voice_name, tmp_file, speed)
        segment = AudioSegment.from_file(tmp_file)
        combined += segment + AudioSegment.silent(duration=150)  # pausa entre frases
        os.remove(tmp_file)

    combined.export(output_path, format="mp3")

# === Dividir por Capítulos ===
def split_by_chapters(text):
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
        self.root.geometry("720x620")
        self.root.minsize(600, 480)
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
        self.voice_frame = tk.Frame(root, relief="groove", bd=1)
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
        self.voice_canvas.bind("<Enter>", lambda e: self.voice_canvas.bind_all("<MouseWheel>", lambda ev: self.voice_canvas.yview_scroll(int(-1*(ev.delta/120)), "units")))
        self.voice_canvas.bind("<Leave>", lambda e: self.voice_canvas.unbind_all("<MouseWheel>"))

        # Velocidade
        tk.Label(root, text="Velocidade:").pack(anchor="w", padx=10)
        self.speed_var = tk.StringVar(value="1.4")
        self.speed_dropdown = ttk.Combobox(root, textvariable=self.speed_var,
                                           values=[str(round(x*0.1,1)) for x in range(10,21)],
                                           state="readonly")
        self.speed_dropdown.pack(fill="x", padx=10)

        # Dividir capítulos
        self.chapter_var = tk.BooleanVar()
        tk.Checkbutton(root, text="Dividir por capítulos", variable=self.chapter_var).pack(anchor="w", padx=10, pady=(5,10))

        # Gerar áudio
        self.generate_btn = tk.Button(root, text="🎧 Gerar Áudio", command=self.start_generate)
        self.generate_btn.pack(pady=5)

        # Barra de progresso
        self.progress = ttk.Progressbar(root, orient="horizontal", length=640, mode="determinate")
        self.progress.pack(pady=10, padx=10)

        self.root.after(100, self.load_voices)

    def select_file(self):
        filepath = filedialog.askopenfilename(title="Selecione o arquivo",
                                              filetypes=[("Arquivos de texto","*.pdf *.txt *.docx"), ("Todos","*.*")])
        if filepath:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, filepath)
            try:
                self.text = extract_text(filepath)
            except Exception as e:
                messagebox.showerror("Erro ao ler arquivo", str(e))
                self.text = None

    def load_voices(self):
        async def load():
            try:
                self.voices = await list_voices()
                for widget in self.voice_inner.winfo_children():
                    widget.destroy()
                for v in self.voices:
                    frame = tk.Frame(self.voice_inner)
                    frame.pack(fill="x", pady=2, padx=2)
                    lbl = tk.Label(frame, text=f"{v.get('ShortName','')} ({v.get('VoiceType','')})", anchor="w")
                    lbl.pack(side="left", padx=5, fill="x", expand=True)
                    tk.Button(frame, text="▶️", command=lambda voice=v: threading.Thread(
                        target=lambda: asyncio.run(preview_voice(voice["ShortName"])), daemon=True).start()).pack(side="left", padx=5)
                    tk.Button(frame, text="Selecionar", command=lambda voice=v: self.select_voice(voice)).pack(side="left", padx=5)
            except Exception as e:
                messagebox.showerror("Erro ao carregar vozes", str(e))
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
        threading.Thread(target=self.generate_audio_thread,
                         args=(self.text, self.selected_voice, out_name, speed, divide_chapters),
                         daemon=True).start()

    def generate_audio_thread(self, text, voice, output_path, speed, divide_chapters):
        self.progress['value'] = 0
        self.progress.update()
        self.audio_done = False

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

        try:
            if divide_chapters:
                chapters = split_by_chapters(text)
                full_text = ""
                for _, content in chapters:
                    full_text += content + "\n"
                asyncio.run(generate_audio(full_text, voice, output_path, speed))
            else:
                asyncio.run(generate_audio(text, voice, output_path, speed))
            self.audio_done = True
            messagebox.showinfo("Pronto!", f"Áudio gerado: {output_path}")
        except Exception as e:
            self.audio_done = True
            messagebox.showerror("Erro ao gerar áudio", str(e))

# === Rodar GUI ===
if __name__ == "__main__":
    root = tk.Tk()
    app = TextToAudioGUI(root)
    root.mainloop()
