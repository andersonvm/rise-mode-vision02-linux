# Vision 02 Studio v14 — Layout físico e janela adaptativa

## O que muda

- A grade **5 × 3** mantém tamanho fixo: teclas de 106 × 116 unidades lógicas, imagens de 86 × 86, espaços de 11 unidades; não se estica quando a janela cresce.
- Corpo externo com gradiente escuro, borda e sombra (efeito **2,5D via GTK/CSS**, não renderização 3D real). Destaques de seleção e pressionamento físico permanecem.
- O conjunto do dispositivo é centralizado nos dois eixos dentro do painel esquerdo, preservando rolagem em janelas pequenas.
- O Studio abre usando cerca de 90% da largura e 84% da altura do monitor, limitado a 1740 × 960, ou utiliza o último tamanho salvo caso caiba na área disponível.
- O último tamanho da janela é persistido em `~/.config/vision02/studio-window.json` (ou em `$XDG_CONFIG_HOME/vision02/studio-window.json`) com permissões 0600. Nenhum YAML é alterado.

## Ícone do GNOME / dock

O identificador GTK já utilizado é `io.github.vision02.Studio`, mas o atalho Debian antigo era `vision02-studio.desktop`. O pacote **vision02-studio-desktop 1.2.0** registra os atalhos `io.github.vision02.Studio.desktop` e `io.github.vision02.StudioManager.desktop` e os ícones SVG sob esses mesmos identificadores. Isso corrige a associação do aplicativo no GNOME/Wayland. Se o dock ainda mostrar um ícone antigo fixado, desfixe-o e fixe o Studio novamente pelo menu.

## Instalação

1. Feche o Vision 02 Studio.
2. Atualize o pacote `.deb` do desktop para a versão `1.2.0-1` (ícone do menu/dock).
3. Abra **Vision 02 — Atualizações**, selecione `vision02-layout-equipamento-v14-update.zip`, inspecione e use **Aplicar e testar**.
4. Reabra **Vision 02 Studio** pelo menu, vá a **Teclas** e confira a representação física compacta, o destaque e o tamanho inicial da janela.
5. Se desejar, redimensione uma única vez, feche sem mudanças não salvas e abra novamente para verificar a persistência.

## Garantias

O pacote de atualização não toca em perfis YAML, ações, scripts pessoais, credenciais OBS, controlador USB/HID ou `vision02.service`. Não executa IPC nem commit. Os quatro arquivos do ZIP são restritos à interface, testes e documentação.

## Validação manual pendente no Ubuntu

Verifique visualmente: 5 colunas × 3 linhas, teclas não esticadas, centralização no painel, ícones legíveis, clique seleciona, pressão física destaca, página de propriedades utilizável com rolagem, janela reabre com tamanho confortável e dock mostra o ícone personalizado.
