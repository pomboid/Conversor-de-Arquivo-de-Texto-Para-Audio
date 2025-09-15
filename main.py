import os
import tempfile
import asyncio
import tkinter as tk
from tkinter import filedialog
from tqdm import tqdm
from pydub import AudioSegment
import fitz  # PyMuPDF
import docx  # python-docx
import edge_tts
from playsound import playsound

# === Função para extrair texto ===
def extract_text(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    text = ""
    if ext == ".pdf":
        print("📖 Extraindo texto do PDF...")
        doc = fitz.open(filepath)
        for page in tqdm(doc, desc="Extraindo páginas", unit="página"):
            text += page.get_text()
    elif ext == ".txt":
        print("📄 Lendo TXT...")
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    elif ext == ".docx":
        print("📑 Extraindo texto do DOCX...")
        doc = docx.Document(filepath)
        for para in tqdm(doc.paragraphs, desc="Lendo parágrafos", unit="parágrafo"):
            text += para.text + "\n"
    else:
        raise ValueError("❌ Tipo de arquivo não suportado. Use PDF, TXT ou DOCX.")
    return text

# === Função para listar vozes do Edge TTS ===
async def list_voices():
    voices = await edge_tts.VoicesManager.create()
    ptb_voices = [v for v in voices.voices if "pt-BR" in v["Locale"]]
    print("\n=== Vozes em Português Disponíveis ===")
    for i, v in enumerate(ptb_voices):
        print(f"[{i}] {v['ShortName']} ({v['VoiceType']})")
    return ptb_voices

# === Função para prévia de voz ===
async def preview_voice(text, voice_name):
    tmp_mp3 = tempfile.mktemp(suffix=".mp3")
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(tmp_mp3)
    playsound(tmp_mp3)
    os.remove(tmp_mp3)

# === Função para gerar áudio completo ===
async def generate_audio(text, voice_name, output_path, speed=1.4):
    tmp_mp3 = tempfile.mktemp(suffix=".mp3")
    print("🎙️ Gerando áudio temporário...")
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(tmp_mp3)

    print(f"⏩ Acelerando áudio ({speed}x) e exportando MP3...")
    sound = AudioSegment.from_file(tmp_mp3)
    faster_sound = sound._spawn(sound.raw_data, overrides={"frame_rate": int(sound.frame_rate * speed)})
    faster_sound = faster_sound.set_frame_rate(sound.frame_rate)
    faster_sound.export(output_path, format="mp3")
    os.remove(tmp_mp3)
    print(f"✅ Áudio gerado com sucesso: {output_path}")

# === Função para dividir texto por capítulos simples ===
def split_by_chapters(text):
    # Assume capítulos começam com "Capítulo" ou "Capitulo"
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

# === MAIN ===
async def main():
    root = tk.Tk()
    root.withdraw()
    filepath = filedialog.askopenfilename(
        title="Selecione o arquivo para converter em áudio",
        filetypes=[("Arquivos de texto", "*.pdf *.txt *.docx"), ("Todos os arquivos", "*.*")]
    )
    if not filepath:
        print("⚠️ Nenhum arquivo selecionado.")
        return

    text = extract_text(filepath)
    ptb_voices = await list_voices()

    # Escolher voz
    while True:
        try:
            idx = int(input("\nDigite o número da voz para ouvir a prévia: "))
            if 0 <= idx < len(ptb_voices):
                preview_text = "Olá, esta é uma prévia da voz."
                await preview_voice(preview_text, ptb_voices[idx]["ShortName"])
                confirmar = input("Gostou dessa voz? (s/n): ").strip().lower()
                if confirmar == "s":
                    selected_voice = ptb_voices[idx]["ShortName"]
                    break
            else:
                print("⚠️ Número inválido, tente novamente.")
        except ValueError:
            print("⚠️ Digite um número válido.")

    # Escolher velocidade
    speed = float(input("Digite a velocidade do áudio (1.0 a 2.0, padrão 1.4): ") or 1.4)

    # Escolher modo: completo ou capítulos
    modo = input("Gerar áudio inteiro ou por capítulos? (c/completo, p/por capítulos): ").strip().lower()
    if modo.startswith("p"):
        chapters = split_by_chapters(text)
        for title, content in chapters:
            out_name = os.path.splitext(os.path.basename(filepath))[0] + f"_{title.replace(' ', '_')}_{speed}x.mp3"
            await generate_audio(content, selected_voice, out_name, speed)
    else:
        out_name = os.path.splitext(os.path.basename(filepath))[0] + f"_1.4x.mp3"
        await generate_audio(text, selected_voice, out_name, speed)

if __name__ == "__main__":
    asyncio.run(main())
