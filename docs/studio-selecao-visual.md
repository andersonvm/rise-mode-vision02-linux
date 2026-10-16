# Vision 02 Studio — seleção visual de elementos (pós e514ee0)

## Objetivo

Conectar o preview editável da aba **Composição** às abas **Imagem** e
**Texto** sem mudar YAML, serviços, controladores HID, OBS ou o IPC.

- **Clique simples sobre uma região de texto visível:** seleciona `Texto`
  no seletor de Composição e abre a aba **Texto**.
- **Clique sobre uma região de imagem:** seleciona `Imagem` e abre **Imagem**.
- **Arraste iniciado sobre o elemento:** seleciona o elemento antes do
  movimento, mantém a aba **Composição** aberta e utiliza os manipuladores
  `Gtk.GestureDrag` e os limites já existentes.
- **Clique/arraste fora de elementos estimados:** não altera a seleção,
  não ativa aparência personalizada e não inicia movimentação.
- **Alça GTK ↘:** permanece independente e continua redimensionando a imagem.
- **Seletor manual Imagem/Texto:** permanece disponível como alternativa.
- **Preview local:** usa o renderizador já existente, sem gravar o perfil.

### Limitação deliberada

O backend entrega um **PNG composto**. Não há uma máscara ou árvore de camadas
que permita diferenciar com precisão os pixels da imagem e do texto. Por isso,
o hit-test implementado em `studio_visual_selection.py` é **aproximado**, usando
escala/posição da imagem, texto/posição, tamanho de fonte, alinhamento e zoom.
Não identifica transparência, glyphs exatos, quebra de linha real, recortes
ou a área efetiva de imagens no modo `contain`. Em casos ambíguos, a área de
texto tem prioridade sobre a imagem. Use o seletor manual para ajustes
precisos. Se futuramente o renderizador expuser bounding boxes efetivas,
substitua somente a função de hit-test, preservando os gestos e o fluxo do Studio.

### Persistência e segurança

Selecionar por clique, mudar de aba, arrastar, usar zoom ou desfazer/refazer
não chama `quick_save`, `reload`, IPC nem operações USB/HID. O salvamento em
YAML continua explícito pelo botão **Salvar YAML com backup** e a aplicação
ao hardware depende de **Aplicar ao dispositivo (IPC)**, como antes.

O instalador valida o SHA-256 do `apps/vision02_studio.py` do commit
`e514ee0` recebido neste pacote, impede sobrescrever revisões locais
diferentes e cria backup antes de qualquer modificação. Se validação ou
testes falharem, tenta restaurar as alterações feitas pelo instalador.

## Teste manual no Ubuntu (não executado automaticamente)

1. Abra `./scripts/vision02-studio` (não reinicie `vision02.service`).
2. Na página **Teclas**, selecione uma tecla que tenha imagem e texto.
3. Vá à aba **Composição** e clique sobre o texto; deve abrir **Texto**.
4. Volte à **Composição** e clique sobre a imagem fora da área textual;
   deve abrir **Imagem**.
5. Volte à **Composição** e arraste a imagem; a aba deve permanecer aberta,
   posições devem mudar e o histórico deve permitir desfazer/refazer.
6. Selecione uma tecla com texto visível, sem imagem, e arraste na área
   textual; deve alterar apenas os deslocamentos de texto.
7. Clique fora de elementos reconhecidos (ex.: próximo da borda, com uma
   imagem pequena); os números de posição não devem mudar.
8. Use a alça ↘ para redimensionar; alterne zoom 100/150/200%.
9. Confira que a troca de abas **não habilita Aplicar IPC** sem salvar;
   ao trocar de tecla com alterações pendentes, mantenha o bloqueio original.
10. Faça testes de salvamento **somente em uma cópia de perfil**, se desejar
    validar persistência. **Não aplique IPC ao hardware** durante estes testes.

## Regressão

O instalador executa `compileall`, `pytest -q` e `git diff --check` sem
criar commits. Como o pacote inclui apenas uma seleção de fontes, os testes
integrais **precisam rodar no repositório local completo**. A validação
pré-entrega foi feita em 131 testes viáveis com os arquivos recebidos.
