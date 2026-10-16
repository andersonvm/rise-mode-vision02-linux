# Vision 02 Studio — Composição Visual v4

Base de referência: commit local `3df4080` (`feature/profiles-actions`).
Instalação incremental sobre a v3, preservando o preview de PNG composto, os
quatro painéis de edição, o hit-test aproximado, o redimensionamento, os gestos,
o histórico, o salvamento YAML com backup e o IPC explícito.

## Recursos

- **Ajuste fino por botões:** selecione Imagem ou Texto na aba **Composição**,
  escolha `1 px` ou `5 px` e use `← ↑ ↓ →`. Uma ação concluída adiciona **uma**
  entrada ao histórico existente (até 64). Ao alcançar o limite sem alterar o
  estado, nenhum histórico é criado.
- **Atalhos restritos à Composição:** `Ctrl+Setas` move 1 px;
  `Ctrl+Shift+Setas` move 5 px. Não intercepta atalhos ao editar um
  `Gtk.Entry`, `Gtk.TextView` ou `Gtk.SpinButton` e não atua fora da página
  **Teclas → Composição**. Os atalhos anteriores de Undo/Redo permanecem.
- **Indicador de coordenadas:** exibe X/Y e, quando aplicável, a escala da
  imagem selecionada. Reflete alterações pelo teclado, botões, campos,
  arraste, desfazer e refazer; a escala não é alterada pelo ajuste fino.
- **Encaixe inteligente configurável:** caixa **Encaixe inteligente no centro
  e nas bordas (sem grade)**. Ativada inicialmente, preserva a v3: o arraste
  sem grade encaixa em âncoras dentro da tolerância existente (`3 px`).
  Desativada, o arraste sem grade é contínuo, sujeito aos limites válidos.
- **Grade existente, preservada:** a opção de 5 px tem precedência no arraste.
  Guias só se destacam quando a coordenada coincide com âncoras relevantes e
  o encaixe inteligente está habilitado. O ajuste fino por botões/atalhos
  **ignora grade e snap** para garantir incremento exato de 1 ou 5 px.

## Limites

- Imagem: X/Y de **-100 a +100**; texto: X/Y de **-40 a +40** (limites já
  existentes nos controles de aparência).
- Não há hit-test pixel a pixel: o backend continua entregando um PNG composto.
- Os marcadores de alinhamento e seleção são sobreposições locais no GTK.
  Não modificam a imagem renderizada nem os LCDs.
- Durante a edição, a alteração do formulário é indicada como não salva,
  conforme o fluxo preexistente. Alterar zoom, prioridade ou a caixa de
  encaixe não altera o YAML por si só.
- Cada clique de ajuste fino cria uma operação de histórico; manter a tecla
  pressionada pode criar diversas entradas. O mecanismo existente limita o
  histórico a 64 operações.

## Validação no Ubuntu/Wayland

1. Feche o Studio anterior e inicie `./scripts/vision02-studio`.
2. Em **Teclas → Composição**, escolha uma tecla que tenha imagem e texto.
3. Selecione **Imagem**. Use botões com passo `1 px` e `5 px`. Verifique o
   indicador X/Y e que a escala continua idêntica.
4. Teste `Ctrl+Setas`, `Ctrl+Shift+Setas` fora de campos editáveis. Verifique
   que setas nos campos numéricos continuam editando o próprio campo.
5. Selecione **Texto**, repita o movimento e confirme o limite ±40 px.
6. Arraste sem grade perto do centro/bordas com encaixe habilitado; desative-o
   e repita. Ative a grade 5 px e confirme o arraste em múltiplos de 5.
7. Use Desfazer/Refazer e confirme a reversibilidade. Verifique a alça ↘,
   a seleção por clique e os zooms 100%, 150% e 200%.
8. Troque de tecla com edição pendente: a proteção de mudanças não salvas deve
   continuar valendo. Evite salvar/aplicar em perfis pessoais durante testes;
   utilize cópias descartáveis.
9. Execute `.venv/bin/python -m pytest -q` e `git diff --check` a partir da
   raiz do repositório.

## Arquivos alterados

- `apps/vision02_studio.py` — integração GTK, atalhos e indicador;
- `src/vision02/studio_composition_v4.py` — operações puras e validação;
- `tests/test_studio_composition_v4.py` — regressão de operações/callbacks;
- `docs/studio-composicao-v4.md` — esta documentação.

O instalador trabalha em modo inspeção por padrão; `--apply` valida hashes,
rejeita alterações locais inesperadas nesses arquivos, faz backup em
`~/.cache/vision02-studio-v4-backups/`, executa a suíte do repositório e
executa rollback dos quatro arquivos se um passo falhar. Não faz commit,
não aplica IPC, não reinicia serviço e não altera YAML, credenciais, systemd
ou código USB/HID.
