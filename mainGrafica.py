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
import concurrent.futures
import math
from tqdm import tqdm
import hashlib
import pickle
import queue
from functools import lru_cache
import gc
from pathlib import Path

# === Funções de Extração de Texto ===
def extract_text(filepath):
    """Extrai texto de arquivos PDF, TXT e DOCX com feedback de progresso."""
    ext = os.path.splitext(filepath)[1].lower()
    text = ""
    
    print(f"📖 Extraindo texto de {os.path.basename(filepath)}...")
    start_time = time.time()
    
    if ext == ".pdf":
        doc = fitz.open(filepath)
        total_pages = len(doc)
        print(f"📄 PDF com {total_pages} páginas")
        
        for page_num, page in enumerate(tqdm(doc, desc="Extraindo páginas", unit="página")):
            text += page.get_text()
        doc.close()
        
    elif ext == ".txt":
        print("📝 Lendo arquivo TXT...")
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
            
    elif ext == ".docx":
        doc = docx.Document(filepath)
        paragraphs = list(doc.paragraphs)
        print(f"📑 DOCX com {len(paragraphs)} parágrafos")
        
        for para in tqdm(paragraphs, desc="Lendo parágrafos", unit="parágrafo"):
            text += para.text + "\n"
            
    else:
        raise ValueError("❌ Tipo de arquivo não suportado. Use PDF, TXT ou DOCX.")
    
    extraction_time = time.time() - start_time
    text_length = len(text)
    print(f"✅ Texto extraído: {text_length:,} caracteres em {extraction_time:.2f}s")
    
    return text.strip()

def print_performance_stats(text_length, processing_time, output_file, chunks_processed=0, cache_hits=0):
    """Exibe estatísticas de performance do processamento."""
    file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
    chars_per_second = text_length / processing_time if processing_time > 0 else 0
    
    print("\n" + "="*60)
    print("📊 ESTATÍSTICAS DE PERFORMANCE AVANÇADAS")
    print("="*60)
    print(f"📝 Caracteres processados: {text_length:,}")
    print(f"⏱️  Tempo total: {processing_time:.2f} segundos")
    print(f"🚀 Velocidade: {chars_per_second:.0f} chars/segundo")
    print(f"📁 Arquivo gerado: {os.path.basename(output_file)}")
    print(f"💾 Tamanho do áudio: {file_size:.2f} MB")
    if chunks_processed > 0:
        print(f"🧩 Chunks processados: {chunks_processed}")
        print(f"⚡ Cache hits: {cache_hits}")
        print(f"📈 Eficiência do cache: {(cache_hits/chunks_processed)*100:.1f}%" if chunks_processed > 0 else "0%")
    print("="*60)

# === Sistema de Cache e Pool de Conexões ===
class AudioCache:
    """Cache inteligente para chunks de áudio processados."""
    def __init__(self, cache_dir=".audio_cache", max_size_mb=100):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.max_size_mb = max_size_mb
        self.cache_stats = {"hits": 0, "misses": 0}
    
    def _get_cache_key(self, text, voice, speed):
        """Gera chave única para o cache."""
        content = f"{text}_{voice}_{speed}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, text, voice, speed):
        """Recupera áudio do cache se existir."""
        cache_key = self._get_cache_key(text, voice, speed)
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    audio_data = pickle.load(f)
                self.cache_stats["hits"] += 1
                return audio_data
            except:
                pass
        
        self.cache_stats["misses"] += 1
        return None
    
    def put(self, text, voice, speed, audio_data):
        """Armazena áudio no cache."""
        cache_key = self._get_cache_key(text, voice, speed)
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(audio_data, f)
        except:
            pass
    
    def cleanup(self):
        """Limpa cache antigo se necessário."""
        if not self.cache_dir.exists():
            return
        
        total_size = sum(f.stat().st_size for f in self.cache_dir.glob("*.pkl"))
        if total_size > self.max_size_mb * 1024 * 1024:
            # Remove arquivos mais antigos
            files = [(f, f.stat().st_mtime) for f in self.cache_dir.glob("*.pkl")]
            files.sort(key=lambda x: x[1])
            
            for f, _ in files[:len(files)//2]:  # Remove metade dos arquivos mais antigos
                f.unlink()

# Instância global do cache
audio_cache = AudioCache()

class TTSConnectionPool:
    """Pool de conexões para Edge TTS."""
    def __init__(self, max_connections=5):
        self.max_connections = max_connections
        self.semaphore = asyncio.Semaphore(max_connections)
        self.active_connections = 0
    
    async def acquire(self):
        """Adquire uma conexão do pool."""
        await self.semaphore.acquire()
        self.active_connections += 1
    
    def release(self):
        """Libera uma conexão do pool."""
        self.semaphore.release()
        self.active_connections -= 1

# Instância global do pool
tts_pool = TTSConnectionPool()

# === Funções de TTS ===
@lru_cache(maxsize=1)
async def list_voices():
    """Lista vozes com cache para evitar requisições repetidas."""
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

def split_text_into_chunks(text, max_chunk_size=5000):
    """
    Divide o texto em chunks menores para processamento mais eficiente.
    Tenta manter frases completas dentro dos chunks.
    """
    if len(text) <= max_chunk_size:
        return [text]
    
    chunks = []
    sentences = re.split(r'([.!?]\s*)', text)
    
    current_chunk = ""
    for i in range(0, len(sentences), 2):
        sentence = sentences[i] + (sentences[i+1] if i+1 < len(sentences) else "")
        
        if len(current_chunk + sentence) <= max_chunk_size:
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

async def generate_audio_chunk_optimized(chunk, voice_name, speed=1.4, chunk_id=0):
    """
    Gera áudio para um chunk específico com otimizações avançadas.
    """
    # Verifica cache primeiro
    cached_audio = audio_cache.get(chunk, voice_name, speed)
    if cached_audio:
        return cached_audio
    
    # Adquire conexão do pool
    await tts_pool.acquire()
    
    try:
        tmp_mp3 = tempfile.mktemp(suffix=".mp3")
        communicate = edge_tts.Communicate(chunk, voice_name)
        await communicate.save(tmp_mp3)
        
        # Carrega e processa áudio
        sound = AudioSegment.from_file(tmp_mp3)
        sound = sound._spawn(sound.raw_data, overrides={"frame_rate": int(sound.frame_rate * speed)})
        sound = sound.set_frame_rate(sound.frame_rate)
        
        # Armazena no cache
        audio_cache.put(chunk, voice_name, speed, sound)
        
        return sound
    finally:
        tts_pool.release()
        if os.path.exists(tmp_mp3):
            os.remove(tmp_mp3)

def process_chunk_batch(chunks_batch, voice_name, speed, batch_id):
    """
    Processa um lote de chunks usando ThreadPoolExecutor.
    """
    def process_single_chunk(chunk_data):
        chunk, chunk_id = chunk_data
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(generate_audio_chunk_optimized(chunk, voice_name, speed, chunk_id))
        finally:
            loop.close()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(process_single_chunk, chunks_batch))
    
    return results

async def generate_audio(text, voice_name, output_path, speed=1.4, progress_callback=None):
    """
    Gera áudio ultra-otimizado com processamento em lotes e cache inteligente.
    """
    start_time = time.time()
    
    # Remove quebras de linha extras e limpa o texto
    text = text.replace("\n", " ").strip()
    
    # Divide o texto em chunks menores para processamento paralelo
    chunks = split_text_into_chunks(text, max_chunk_size=4000)  # Reduzido para melhor cache hit rate
    
    print(f"📊 Processando {len(chunks)} chunks de texto com otimizações avançadas...")
    
    # Processa em lotes para melhor performance
    batch_size = 5
    audio_segments = []
    total_processed = 0
    cache_hits = 0
    
    for batch_start in range(0, len(chunks), batch_size):
        batch_end = min(batch_start + batch_size, len(chunks))
        batch_chunks = chunks[batch_start:batch_end]
        
        if progress_callback:
            progress_callback(f"Processando lote {batch_start//batch_size + 1}/{(len(chunks)-1)//batch_size + 1}")
        
        # Processa lote usando ThreadPoolExecutor
        batch_data = [(chunk, i + batch_start) for i, chunk in enumerate(batch_chunks)]
        batch_results = process_chunk_batch(batch_data, voice_name, speed, batch_start//batch_size)
        
        audio_segments.extend(batch_results)
        total_processed += len(batch_chunks)
        
        # Força garbage collection para liberar memória
        gc.collect()
    
    # Conta cache hits
    cache_hits = audio_cache.cache_stats["hits"]
    
    if progress_callback:
        progress_callback("Combinando segmentos de áudio...")
    
    # Combina todos os segmentos com streaming
    combined = AudioSegment.silent(duration=0)
    for i, segment in enumerate(audio_segments):
        combined += segment
        # Adiciona pausa entre chunks (exceto no último)
        if i < len(audio_segments) - 1:
            combined += AudioSegment.silent(duration=250)  # Pausa reduzida
    
    if progress_callback:
        progress_callback("Exportando arquivo final...")
    
    # Exporta com compressão otimizada
    combined.export(output_path, format="mp3", bitrate="128k")
    
    processing_time = time.time() - start_time
    print(f"✅ Áudio gerado com sucesso: {output_path}")
    print(f"⚡ Cache hits: {cache_hits}/{total_processed} ({(cache_hits/total_processed)*100:.1f}%)")
    
    return processing_time, total_processed, cache_hits

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
        self.progress_text = ""

        def progress_callback(message):
            """Callback para atualizar o progresso real"""
            self.progress_text = message
            # Atualiza progresso baseado na mensagem
            if "Processando chunk" in message:
                # Extrai número do chunk
                try:
                    chunk_num = int(message.split("chunk ")[1].split("/")[0])
                    total_chunks = int(message.split("/")[1].split("}")[0])
                    progress_value = (chunk_num / total_chunks) * 80  # 80% para processamento
                    self.progress['value'] = progress_value
                except:
                    pass
            elif "Combinando" in message:
                self.progress['value'] = 85
            elif "Exportando" in message:
                self.progress['value'] = 95
            self.progress.update()

        def progress_sim():
            """Simula progresso quando não há callback real"""
            while not self.audio_done:
                if not self.progress_text:  # Só simula se não há progresso real
                    self.progress['value'] += 1
                    if self.progress['value'] > 99:
                        self.progress['value'] = 99
                    self.progress.update()
                time.sleep(0.1)
            self.progress['value'] = 100
            self.progress.update()
        
        threading.Thread(target=progress_sim, daemon=True).start()

        try:
            start_time = time.time()
            
            if divide_chapters:
                chapters = split_by_chapters(text)
                full_text = ""
                for _, content in chapters:
                    full_text += content + "\n"
                processing_time, chunks_processed, cache_hits = asyncio.run(generate_audio(full_text, voice, output_path, speed, progress_callback))
            else:
                processing_time, chunks_processed, cache_hits = asyncio.run(generate_audio(text, voice, output_path, speed, progress_callback))
            
            text_length = len(text)
            
            # Exibe estatísticas no console
            print_performance_stats(text_length, processing_time, output_path, chunks_processed, cache_hits)
            
            self.audio_done = True
            cache_efficiency = (cache_hits/chunks_processed)*100 if chunks_processed > 0 else 0
            messagebox.showinfo("Pronto!", f"Áudio gerado: {output_path}\\n\\nProcessado {text_length:,} caracteres em {processing_time:.2f}s\\nCache: {cache_hits}/{chunks_processed} ({cache_efficiency:.1f}%)")
        except Exception as e:
            self.audio_done = True
            messagebox.showerror("Erro ao gerar áudio", str(e))

# === Funções de Inicialização e Limpeza ===
def initialize_system():
    """Inicializa o sistema com otimizações."""
    print("🚀 Inicializando sistema otimizado...")
    
    # Limpa cache antigo
    audio_cache.cleanup()
    
    # Configura garbage collection
    gc.set_threshold(700, 10, 10)
    
    print("✅ Sistema inicializado com otimizações ativas")
    print(f"📁 Cache: {audio_cache.cache_dir}")
    print(f"🔗 Pool de conexões: {tts_pool.max_connections} conexões máximas")

def cleanup_system():
    """Limpa recursos do sistema."""
    print("🧹 Limpando recursos do sistema...")
    audio_cache.cleanup()
    gc.collect()
    print("✅ Limpeza concluída")

# === Rodar GUI ===
if __name__ == "__main__":
    try:
        initialize_system()
        root = tk.Tk()
        app = TextToAudioGUI(root)
        root.mainloop()
    finally:
        cleanup_system()
