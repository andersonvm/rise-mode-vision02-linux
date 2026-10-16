# Vision 02 Studio — Composição Visual v3

Base: `8cef167` (`feature/profiles-actions`). Instalação incremental que preserva
os recursos anteriores de composição, seleção por clique, arraste,
redimensionamento pela alça GTK, undo/redo e preview local.

## Novidades

- **Regiões de seleção compartilhadas** em
  `studio_visual_selection.visual_element_regions`: a mesma geometria do hit-test
  é usada para desenhar a moldura da seleção no `Gtk.DrawingArea`.
- **Moldura contextual**: ciano para Imagem, âmbar para Texto, com contorno
  escuro para facilitar o contraste; representa a **área selecionável estimada**.
- **Seleção atual**: texto acessível abaixo do seletor manual.
- **Priorizar imagem quando imagem e texto se sobrepõem**: caixa de seleção na
  aba Composição. Desligada, Texto tem prioridade; ligada, Imagem tem
  prioridade. Não altera aparência, YAML, histórico nem status de edição.
- **Recorte por viewport**: regiões estimadas fora do quadro são limitadas ao
  espaço efetivamente disponível durante zoom 100%, 150% e 200%.

## Limites de precisão

O backend fornece somente um **PNG composto**: não existem IDs de camadas,
máscaras de alfa individuais nem medidas reais da fonte. Assim, hit-test e
moldura continuam **aproximados**, especialmente com transparência, recorte,
modo *contain*, quebra de linha e glifos específicos. Uma área pequena dentro
do retângulo pode estar visualmente transparente. A moldura marca a *região
interativa estimada*, não os limites exatos dos pixels. Use o seletor manual
Imagem/Texto ou a opção de prioridade em casos ambíguos.

As guias e molduras são desenhadas pelo Cairo em uma `Gtk.DrawingArea`
transparente, **não** no arquivo PNG nem no dispositivo. Em sessões nas quais
a camada Cairo não aparece, o rótulo **Seleção atual** e o seletor manual
continuam funcionando; validar esse desenho diretamente no Ubuntu/Wayland.

## Segurança e persistência

A seleção, moldura, zoom e prioridade são **exclusivamente locais** ao Studio.
Nenhum evento novo salva YAML, aplica IPC, executa ações de teclas ou acessa
USB/HID. Os botões originais **Salvar YAML com backup** e **Aplicar ao
dispositivo (IPC)** permanecem como as únicas ações correspondentes.

O instalador valida o hash dos dois arquivos-base modificados, não altera
scripts de diagnóstico/perfis, cria backup antes da alteração e testa todo o
repositório. Se falhar, tenta restaurar **apenas** os quatro arquivos da v3.
Não efetua commit nem reinicia `vision02.service`.

## Validação manual (necessária)

1. Feche o Studio e abra `./scripts/vision02-studio` após instalar.
2. Abra **Teclas → Composição** com uma tecla que possua imagem e texto.
3. Selecione Imagem e Texto no seletor: o rótulo muda e deve haver moldura
   ciano/âmbar conforme o elemento. Faça o mesmo em zoom 100/150/200%.
4. Clique no texto e, depois, na imagem. As abas Texto/Imagem devem abrir
   sem aplicar alterações ao hardware.
5. Volte à Composição e clique na área sobreposta: a prioridade é do Texto;
   marque **Priorizar imagem…** e repita, agora selecionando Imagem.
6. Arraste imagem e texto. Confira que as posições mudam e desfazer/refazer
   funcionam. Confira que a alça ↘ continua redimensionando.
7. Confira que selecionar e mudar a prioridade **não habilita Aplicar IPC**.
8. Para verificar salvamento, utilize cópia descartável de perfil. Não faça
   testes de aplicação IPC no hardware de produção.
9. Rode `.venv/bin/python -m pytest -q` e `git diff --check`.

## Arquivos da entrega

- `apps/vision02_studio.py` (atualizado)
- `src/vision02/studio_visual_selection.py` (atualizado)
- `tests/test_studio_composition_v3.py` (novo)
- `docs/studio-composicao-v3.md` (novo)
