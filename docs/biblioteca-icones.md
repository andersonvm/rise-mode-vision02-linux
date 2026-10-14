# Biblioteca de ícones do Vision 02

O editor GTK apresenta as 15 teclas físicas em uma grade de cinco colunas e três linhas. A tecla selecionada fica destacada; o número e o rótulo são exibidos em cada posição. A grade mantém o mapeamento físico → LCD atual, sem alterar o driver.

## Como importar

1. Execute `./scripts/vision02-editor`.
2. Escolha um perfil e clique na tecla física a configurar.
3. Ao lado do campo **Imagem**, clique em **Biblioteca…**.
4. Escolha **Importar imagem…** e selecione um arquivo PNG, JPEG ou WEBP de até 15 MiB e 20 megapixels.
5. A imagem será centralizada e cortada para preencher 100 × 100 pixels, convertida para PNG RGB; transparência é composta sobre o fundo escuro. O original permanece inalterado.
6. Clique no ícone importado para associá-lo à tecla. O caminho é inserido no formulário e a miniatura é atualizada localmente.
7. Configure **Rótulo** e **Ação**, escolha **Pré-visualizar**, depois **Salvar YAML** e **Aplicar ao dispositivo**.

**Importar ou selecionar um ícone não modifica o YAML nem o hardware.** Um ícone só é gravado no perfil quando a tecla tem rótulo e ação configurados e o usuário salva. Se houver alterações não salvas, o editor bloqueará a troca de tecla ou de perfil.

## Diretórios

- Ícones reutilizáveis: `${XDG_DATA_HOME:-~/.local/share}/vision02/assets/icons/`.
- YAML pessoais: `~/.config/vision02/profiles/` (ou `XDG_CONFIG_HOME`).
- As imagens são referenciadas por caminho absoluto nos YAML e podem ser reutilizadas em vários perfis.
- Imagens com pixels finais idênticos são deduplicadas automaticamente.
- A biblioteca não exclui ícones automaticamente, evitando quebrar referências existentes.

## Comportamento e limitações

- O driver USB/HID, o serviço systemd, o IPC e o supervisor permanecem inalterados.
- A seleção visual da tecla é local ao editor; não executa a ação correspondente no dispositivo.
- Esta versão não edita cores e textos diretamente na imagem; a personalização avançada de aparência pode ser implementada em etapa posterior.
- Não há importação/exportação de coleções ou remoção de ícones nesta versão.
