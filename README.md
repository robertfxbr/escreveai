# YouTube para Markdown

App local para transcrever vídeos ou playlists do YouTube e salvar um Markdown por vídeo na pasta escolhida. Pode ser usado pela janela ou pelo terminal.

## Iniciar no Windows

1. Tenha Python 3.10 ou superior e Node.js instalados. Deixe os dois disponíveis no `PATH`. FFmpeg também é recomendado para formatos de áudio que precisam de pós-processamento.
2. Dê dois cliques em `iniciar.bat`. Na primeira execução, o script cria `.venv` e instala as dependências.
3. Cole o link de um vídeo ou playlist, selecione a pasta e clique em **Transcrever**.

## Usar pelo terminal

Após executar `iniciar.bat` uma vez para instalar as dependências:

```powershell
.\.venv\Scripts\python.exe transcrever.py "https://www.youtube.com/playlist?list=ID_DA_PLAYLIST" --pasta "C:\Caminho\Das\Notas"
```

Para um vídeo só, passe o link dele no lugar da playlist. Sem argumentos, o comando pede o link e salva na pasta atual. Use `--whisper` para transcrever diretamente o áudio, mesmo quando existem legendas. Use `--modelo tiny`, `base`, `small` ou `medium` para escolher o modelo. `--limpar-cacoetes` remove apenas cacoetes comuns no início dos trechos; por padrão, nenhuma fala é descartada.

Se o YouTube exigir login para baixar o áudio, exporte apenas os cookies de `youtube.com` em formato Netscape `cookies.txt` seguindo a [FAQ do yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp). Selecione o arquivo no campo **Cookies do YouTube** da janela ou informe `--cookies "C:\Caminho\cookies.txt"` no terminal. Guarde esse arquivo fora do repositório e da pasta de transcrições; ele contém dados de sessão da sua conta. O app também tenta uma rota alternativa de áudio quando a rota padrão falha.

## Contexto visual opcional

Marque **Adicionar contexto visual com Gemini** na janela e informe sua chave da [Gemini API](https://aistudio.google.com/app/apikey). A chave também pode vir da variável de ambiente `GEMINI_API_KEY`; o app não a salva em arquivo. Para usar pelo terminal, defina essa variável no seu ambiente e execute:

```powershell
.\.venv\Scripts\python.exe transcrever.py "https://www.youtube.com/playlist?list=ID_DA_PLAYLIST" --pasta "C:\Caminho\Das\Notas" --visao --limite 3
```

O app envia o link público do vídeo ao Gemini em [modo de análise seletiva](https://ai.google.dev/gemini-api/docs/video-understanding). A resposta é anexada ao mesmo `.md` em **Contexto visual**, separada da transcrição falada. As observações geradas por IA devem ser conferidas no vídeo, sobretudo textos pequenos e marcas de tempo.

O limite padrão é de **3 vídeos novos por execução**. Para playlists longas, rode novamente nos dias seguintes: transcrições e contextos visuais já concluídos são reconhecidos e pulados, inclusive quando o arquivo mantém um nome antigo e contém o link de origem no cabeçalho. Uma análise visual em andamento pode ser retomada pelo identificador salvo na pasta. Use `--limite 0` no terminal para remover o limite por execução. Segundo a [documentação atual do Gemini](https://ai.google.dev/gemini-api/docs/video-understanding), o nível gratuito aceita até 8 horas de vídeo do YouTube por dia e apenas vídeos públicos. Limites e preços podem mudar; confira a [página de preços](https://ai.google.dev/gemini-api/docs/pricing) antes de usar um plano pago.

Se a análise visual falhar, o `.md` com a transcrição permanece na pasta. Execute novamente para tentar acrescentar apenas o contexto visual. O modo de transcrição sem análise visual continua disponível sem chave de API.

O app tenta primeiro obter as legendas disponíveis com `youtube-transcript-api`, priorizando português e inglês. Se não houver legendas acessíveis, baixa apenas o áudio com `yt-dlp` e transcreve com `faster-whisper`. O modelo de fala é baixado automaticamente na primeira vez em que o fallback é usado. O padrão `small` oferece um equilíbrio entre velocidade e qualidade. `tiny` e `base` são mais rápidos; `medium` costuma ser mais preciso e exige mais memória. A detecção do idioma no Whisper é automática. O processo pode demorar em vídeos longos.

O `.md` contém link, duração e todos os trechos de fala com marcas de tempo clicáveis. Em playlists, o título de cada vídeo é usado no arquivo; num link individual processado só pelas legendas, o ID é usado como título. Transcrições já existentes são reconhecidas e puladas, sem sobrescrever arquivos. O áudio temporário é removido ao terminar. Se um vídeo da playlist falhar, o app segue para o próximo e apresenta as falhas no fim.

Vídeos privados, com restrição regional ou indisponíveis para download podem falhar. A precisão depende das legendas ou da qualidade do áudio. Use o app apenas com vídeos cujo conteúdo você tem permissão para acessar e transcrever.

## Desenvolvimento

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-vision.txt
.\.venv\Scripts\python.exe app.py
python -m unittest discover -s tests -v
```
