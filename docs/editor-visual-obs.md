# Editor visual de cenas e mixer OBS — Vision 02

Executar `./scripts/vision02-obs-visual`, ou acessar **Editor visual de cenas e áudio** no painel OBS.

- As teclas físicas são exibidas em grade **5×3**, do número 01 ao 15.
- Em **OBS — Cenas**, arraste cenas da coluna lateral até as teclas 01–14. Arrastar uma tecla sobre outra **troca** as posições. A tecla 15 é reservada para retornar ao Controle.
- Em **OBS — Áudio**, arraste fontes para as teclas 01–12. As teclas 13–15 ficam reservadas para navegação.
- Como alternativa à operação de arrastar, selecione uma cena/fonte na coluna lateral e clique na tecla desejada.
- **Salvar layout no YAML** cria backup e valida todo o catálogo sob lock, com verificação de versão para recusar edições concorrentes.
- **Aplicar ao dispositivo** faz `control reload` por IPC, sem reiniciar o serviço. Nenhuma cena é alterada no OBS ao salvar.
- Ícones e aparência existentes nas posições ocupadas são preservados; limpar uma tecla remove sua configuração correspondente. A tecla de navegação e outros perfis não são modificados.
- **Mixer OBS**: consulta os níveis/mute atuais das entradas. Clique **Aplicar volume** (0–100%, escala multiplicadora linear 0–1 do OBS) ou **Silenciar/Ativar** para modificar apenas a fonte selecionada. Essas operações **alteram de fato o OBS**, mas não o volume global do Ubuntu. Não há ajuste automático ao arrastar o controle deslizante.
- O estado das cenas e das fontes é atualizado no painel. A imagem física usa os indicadores implementados anteriormente, quando o perfil correspondente estiver ativo.

Requisitos: serviço `vision02.service` em execução, perfis `OBS — Cenas` e `OBS — Áudio` já criados e OBS Studio com WebSocket configurado em `~/.config/vision02/obs.json`.

Nenhuma credencial é exibida ou copiada para o YAML. O instalador atualiza apenas o código versionado; os perfis pessoais só serão modificados após a confirmação na janela.
