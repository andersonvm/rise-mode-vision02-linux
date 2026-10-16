# Vision 02 Studio — Camadas lógicas de composição v5

Base exata: `892779e` (`feature/profiles-actions`), com a Composição Visual v4.

## O que mudou

- A aba **Teclas → Composição** possui uma seção **Camadas — seleção local**
  com as opções **Imagem** e **Texto**. Cada opção é habilitada somente se a
  propriedade correspondente existe: caminho de imagem não vazio; texto não
  vazio e opção *Exibir texto* ativa. Para texto, aplica-se o mesmo fallback
  `texto exibido → rótulo` utilizado pelo preview anterior.
- O botão selecionado recebe destaque do tema Adwaita. A lista acompanha as
  mudanças de tecla, imagem, texto e preferências visuais; fica inativa
  enquanto a tecla não foi carregada ou durante um salvamento.
- Selecionar uma camada mantém o usuário na aba Composição e sincroniza o alvo
  do seletor existente. Em áreas sobrepostas, usa a preferência de hit-test
  existente para priorizar a camada explicitamente escolhida.
- Depois de clicar em uma **sobreposição** no preview, pode-se voltar à aba
  Composição e clicar em **Alternar camada no último ponto sobreposto**.
  A alternância só é habilitada enquanto as **duas regiões** calculadas
  coincidirem naquele ponto. Se a geometria mudou, ela é recalculada e a
  alternância é bloqueada. Trocar de tecla descarta o último ponto.
- A moldura ciano/âmbar da camada ativa é preservada. Pequenas marcas nos
  cantos indicam a região aproximada da camada **não selecionada**, quando
  presente; elas são desenhadas apenas na sobreposição GTK local.

## Sem z-order editável

As camadas são **lógicas**, não planos de composição independentes. O
renderizador atual entrega **um PNG composto**: não disponibiliza máscaras,
bounding boxes reais por elemento ou alteração de ordem. A ordem de desenho
permanece **Imagem atrás do Texto**, e a seleção não altera a imagem gravada
no LCD. Os contornos de seleção derivam da geometria aproximada da v3, não
fazem detecção pixel a pixel, e podem exceder a arte ou a fonte renderizada.

## Garantias

O módulo puro `studio_layers_v5.py` não importa GTK e não acessa disco, perfis,
IPC nem HID. Selecionar ou alternar camadas **não adiciona histórico**, **não
marca a tecla como alterada** e **não salva YAML**. Arrastar, redimensionar,
zoom, guias, encaixe, ajuste fino de 1/5 px e Undo/Redo continuam na lógica
existente da v4. Alterações de posição ou tamanho seguem o fluxo de
salvamento explícito com backup e aplicação IPC separada.

## Verificação manual Ubuntu / Wayland

1. Feche a instância anterior, depois execute `./scripts/vision02-studio`.
2. Abra **Teclas → Composição** e selecione uma tecla com imagem e texto
   habilitado. Confira os dois botões e o destaque do botão selecionado.
3. Escolha **Imagem** pela lista; confira que o seletor tradicional também
   mostra Imagem e que a moldura correspondente está ativa. Repita para Texto.
4. Clique no preview numa área onde imagem e texto se sobrepõem. O clique abre
   as propriedades da camada; retorne à Composição e use **Alternar camada no
   último ponto sobreposto**. Verifique alternância nas duas direções.
5. Clique fora de regiões sobrepostas: o botão de alternância deve ficar
   desabilitado. Remova temporariamente o texto da edição (sem salvar) ou
   desmarque *Exibir texto* e confirme que a camada Texto fica indisponível.
6. Teste arraste, alça ↘, zoom 100/150/200%, atalhos Ctrl+Setas e
   Ctrl+Shift+Setas, grade, encaixe e Undo/Redo. A moldura acompanha as
   alterações; os marcadores são apenas locais.
7. Troque de tecla **somente após descartar alterações pendentes** e valide
   que o último ponto de sobreposição não é reutilizado.
8. Sem aplicar IPC nem salvar perfis pessoais, execute:

   ```bash
   cd ~/projetos/rise-mode-vision02/rise-mode-vision02-linux
   .venv/bin/python -m pytest -q
   git diff --check
   ```

## Instalação / recuperação

`instalar_camadas_v5_vision02.py` começa em modo inspeção; `--apply` compara
hashes SHA-256 do arquivo principal e dependências v4, exige ausência de
alterações preparadas nos caminhos da atualização, faz backup em
`~/.cache/vision02-studio-v5-backups/` e executa compilação, `pytest -q`
e verificação de espaços/conflictos. Falhas produzem rollback dos quatro
arquivos alterados. O instalador não executa commit, IPC nem reinício de
serviço, tampouco modifica os perfis YAML ou scripts de diagnóstico.

Arquivos da atualização:

- `apps/vision02_studio.py` — controles GTK e navegação por camada;
- `src/vision02/studio_layers_v5.py` — regras puras;
- `tests/test_studio_layers_v5.py` — regressão de seleção/alternância;
- `docs/studio-camadas-v5.md` — esta documentação.
