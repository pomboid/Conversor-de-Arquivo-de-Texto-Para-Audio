# 🗣️ Text to Speech (TTS) - PDF, TXT e DOCX → MP3  

Este projeto converte arquivos de texto (📄 **PDF**, 📝 **TXT** e 📘 **DOCX**) em áudio **MP3** utilizando o serviço **Edge TTS** da Microsoft.  

👉 Ele possui **duas versões**:
1. **Versão Terminal (CLI)** – executada pelo prompt/terminal (`main.py`).  
2. **Versão com Interface Gráfica (GUI)** – utilizando **Tkinter** (`mainGrafica.py`).

3. OBS: A barra de progresso pode ficar travada no fim, porém é só esperar, quanto maior o arquivo mais tempo leva para converter
4. OBS 2: Indico usar a versão gráfica, esta mais atualizada e mais flúida

---

## 🚀 Funcionalidades
- Suporte a arquivos **PDF, TXT e DOCX**.  
- Escolha de diferentes **vozes em português (pt-BR)**.  
- Ajuste de **velocidade** da fala.  
- Possibilidade de **pré-escutar** uma voz antes de selecionar.  
- Opção de **dividir por capítulos** (quando o texto contiver seções iniciadas por "Capítulo").  
- Barra de progresso na versão GUI.  

---

## 🛠️ Instalação

1. Clonar o repositório
bash
git clone https://github.com/pomboid/Conversor-de-Arquivo-de-Texto-Para-Audio
cd seu-repositorio
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

🔹 Versão Terminal (CLI) – main.py
python main.py 

Ele vai:
-Perguntar o caminho do arquivo.
-Listar vozes disponíveis.
-Gerar o áudio no formato MP3.

🔹 Versão Gráfica (GUI) – mainGrafica.py
python mainGrafica.py

Na interface:
-Clique em Selecionar Arquivo e escolha um PDF, TXT ou DOCX.
-Escolha a voz desejada (teste antes clicando em ▶️).
-Ajuste a velocidade no menu suspenso.
-(Opcional) Marque "Dividir por capítulos".
-Clique em 🎧 Gerar Áudio.
-Aguarde até a barra de progresso chegar em 100%.

📦 projeto-tts
 ┣ 📜 requirements.txt   # Dependências
 ┣ 📜 README.md          # Documentação
 ┣ 📜 main.py            # Versão terminal (CLI)
 ┣ 📜 mainGrafica.py     # Versão com interface gráfica (GUI)

⚡ Observações

-Necessário ter Python 3.8+ ou superior instalado.
-O áudio gerado será salvo no mesmo diretório do arquivo selecionado.
-Na GUI, a prévia da voz usa um texto curto fixo. Já a geração final pode usar um texto maior.

👨‍💻 Autor
Desenvolvido por pomboid 🐦
