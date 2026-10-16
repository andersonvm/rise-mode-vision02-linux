# Vision 02 Studio — Controles avançados de camadas v6

**Base:** `42083e2` na branch `feature/profiles-actions`; GTK4 com camadas lógicas v5.

## Novos controles

Na seção **Teclas → Composição → Camadas — seleção local**:

- **Bloquear Imagem / Bloquear Texto**: impede novas operações de arrastar, redimensionar, ajuste fino de 1/5 px, centralizar X/Y, restaurar geometria e edição direta dos campos numéricos X/Y/escala da camada bloqueada. O botão de alça é ocultado para imagem bloqueada. A seleção de camadas continua disponível. **Desfazer/Refazer** permanece intencionalmente disponível, inclusive quando a camada está bloqueada, para recuperar mudanças anteriores.
- **Mostrar moldura Imagem / Mostrar moldura Texto**: oculta ou exibe apenas **os indicadores de seleção GTK**, incluindo os cantos discretos da camada não selecionada. **Não oculta o conteúdo no PNG ou no LCD**. Os elementos continuam selecionáveis mesmo que sua moldura esteja invisível.
- **Centralizar X / Centralizar Y**: opera sobre a camada selecionada. Na Imagem, coloca o centro da caixa da imagem no centro do LCD no eixo correspondente (`image_x=0` ou `image_y=0`). No Texto, estima a caixa através da mesma geometria da seleção visual existente e calcula um deslocamento compatível com o alinhamento textual atual (`left/center/right`, `top/center/bottom`). O valor é limitado às faixas GTK atuais (imagem ±100 px, texto ±40 px). É uma **centralização aproximada**, não uma medição tipográfica exata.
- **Restaurar posição/tamanho do elemento**: controle já existente da v2, agora desabilitado enquanto a camada correspondente estiver bloqueada.

Bloqueio e molduras são **estado local da janela**: iniciar a edição de outra tecla limpa esses estados. Eles não integram o YAML, não criam histórico e não são aplicados via IPC. Centralizar modifica somente as coordenadas existentes na edição em memória: marca alterações quando necessário e participa do `CompositionHistory` para Undo/Redo. O salvamento do YAML exige o botão explícito **Salvar YAML com backup**; a aplicação ao dispositivo permanece separada.

## Limitação do renderizador

O backend fornece **somente um PNG composto**, sem canais independentes por elemento. Portanto esta v6 **não oferece visibilidade real da arte por camada**: mudar a visibilidade das molduras não deve ser confundido com ocultar imagem ou texto. Para ocultar o conteúdo individual, seria necessária uma alteração posterior do renderizador com prévias independentes. A ordem permanece **Imagem → Texto**, sem z-order editável.

## Verificação manual no Ubuntu / Wayland

1. Feche o Studio existente e execute `./scripts/vision02-studio` no projeto; abra **Teclas → Composição**.
2. Selecione uma tecla com imagem e texto. Bloqueie Imagem e tente arrastá-la, usar `Ctrl+Setas`, os botões ←↑↓→, centralizar e a alça ↘. Nenhum desses controles deve alterar os valores da imagem; a alça deve desaparecer.
3. Desbloqueie a Imagem e confirme que o ajuste fino, arraste, centralização e Undo/Redo voltam a funcionar. Os comandos de centralização podem não modificar um eixo que já esteja centralizado.
4. Selecione Texto e repita bloqueio/desbloqueio; valide centralização de texto para alinhamentos esquerdo/central/direito e superior/central/inferior, lembrando que o posicionamento é uma estimativa.
5. Desmarque **Mostrar moldura Imagem** e/ou **Mostrar moldura Texto**. Apenas os contornos locais devem desaparecer; **a imagem e o texto continuam no preview composto**.
6. Sem alterações não salvas, troque de tecla. Bloqueios e visibilidade das molduras retornam ao padrão: desbloqueados e mostrados.
7. Teste Desfazer/Refazer e os comandos da v4/v5. Não salve nem aplique IPC para validar a seleção/bloqueio.
8. Execute `.venv/bin/python -m pytest -q`, `git diff --check`, `git status --short` no diretório do projeto.

## Instalação e recuperação

O instalador `instalar_camadas_v6_vision02.py` começa em **modo inspeção**. A execução com `--apply` verifica os hashes SHA-256 dos arquivos-base, recusa alterações locais conflitantes ou destino pré-existente, salva backup em `~/.cache/vision02-studio-v6-backups/`, aplica quatro arquivos e executa `compileall`, a suíte completa `pytest -q` e `git diff --check`. Em caso de falha, restaura o arquivo alterado e apaga os novos. Não faz commit nem chama IPC, HID ou systemd. **Não inclui nem edita YAML, credenciais OBS ou scripts de diagnóstico.**

Arquivos modificados/criados:

- `apps/vision02_studio.py` — painel GTK, bloqueios e ações.
- `src/vision02/studio_layers_v6.py` — regras puras de bloqueio e centralização.
- `tests/test_studio_layers_v6.py` — testes de regressão.
- `docs/studio-camadas-v6.md` — este documento.
