# Vision 02 — Perfil OpenBoard 1.0

Perfil com **15 teclas** e imagens próprias para o Stream Deck Rise Mode Vision02 (Studio v15).

## Mapeamento

| Tecla | Recurso | Ação |
| --- | --- | --- |
| 01 | Abrir OpenBoard | Inicia `OpenBoard` ou `openboard` (também procura Flatpak) |
| 02 | Caneta | Ctrl+P |
| 03 | Borracha | Ctrl+E |
| 04 | Marca-texto | Ctrl+M |
| 05 | Seleção | Ctrl+F |
| 06 | Texto | Ctrl+K |
| 07 | Ponteiro laser | Ctrl+G |
| 08 | Desfazer | Ctrl+Z |
| 09 | Refazer | Ctrl+Y |
| 10 | Nova página | Insert |
| 11 | Página anterior | Seta esquerda |
| 12 | Próxima página | Seta direita |
| 13 | Modo quadro | Ctrl+B |
| 14 | Modo desktop | Ctrl+Shift+H |
| 15 | Menu de Perfis | Ação nativa `type: profile`, `target: Menu de Perfis` |

Atalhos baseados na documentação do **OpenBoard-org**: <https://github.com/OpenBoard-org/OpenBoard/wiki/Parameters> e <https://github.com/OpenBoard-org/OpenBoard/discussions/1233>. Alguns atalhos variam por versão ou personalização.

## Instalação gráfica (.deb)

1. Instale o `.deb` pelo instalador de pacotes do Ubuntu.
2. No menu de aplicativos, abra **Vision 02 — Perfil OpenBoard**.
3. Clique em **Instalar perfil OpenBoard**.
4. Abra **Vision 02 Studio → Menu de Perfis**.
5. Clique em **Inspecionar catálogo → Sincronizar menu e tecla 15**; confirme a mudança e **Recarregar catálogo (IPC)**.
6. Abra **Menu de Perfis nos LCDs (IPC)** e selecione OpenBoard.

**Importante:** instalar o `.deb` não altera os perfis do usuário por si só; a instalação do perfil ocorre quando o usuário executa o assistente. O Menu de Perfis precisa ser sincronizado após adicionar o OpenBoard para que ele apareça nas teclas.

## Instalação portátil (ZIP)

Extraia o ZIP e execute `python3 install.py` no diretório extraído para abrir a interface. Também aceita `python3 install.py --inspect` e `python3 install.py --apply`. O modo CLI requer `python3-yaml`; a interface requer GTK4 e PyGObject (`python3-gi`, `gir1.2-gtk-4.0`).

**Nunca** use o gerenciador de **atualização do código** do Studio para este ZIP: ele contém **um perfil de usuário**, não uma atualização do programa.

## Segurança

- Perfil em `~/.config/vision02/profiles/openboard.yaml`.
- Ícones em `~/.config/vision02/profile-icons/openboard/`.
- Script de abertura em `~/.config/vision02/profile-tools/launch-openboard.sh`.
- Backup antes de qualquer substituição em `~/.local/state/vision02/openboard-backups/`.
- Se o YAML OpenBoard já existir, o instalador não sobrescreve por padrão.
- Nenhum outro perfil ou configuração de tecla 15 é modificado. Essa atualização coletiva só ocorre quando o usuário sincroniza o menu no Studio v15.
- Não executa comandos administrativos, não modifica USB/HID e não reinicia serviços.

## Observações sobre atalhos

Os atalhos são enviados à **janela atualmente em foco**. Deixe o OpenBoard em primeiro plano. Em sessões GNOME/Wayland, o Vision02 pode solicitar autorização de controle de teclado por meio do portal de desktop. Não configure combinações conflitantes com o ambiente gráfico.
