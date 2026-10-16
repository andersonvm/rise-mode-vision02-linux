# Edição rápida integrada ao Vision 02 Studio

Na seção **Teclas**, selecione uma tecla física para abrir as propriedades na
coluna lateral. O campo **Texto visual no LCD** permite sobrepor um título
à imagem, preservando as demais opções de aparência. A grade continua sendo um espelho dos JPEG transmitidos pelo
serviço Vision 02; não há segunda conexão USB/HID.

O painel usa as mesmas funções de inspeção, validação e gravação do editor
avançado (`vision02_editor_backend`). Os campos disponíveis são rótulo,
imagem (caminho local ou biblioteca) e ação (`none`, `command`, `url`, `script`,
`hotkey`, `profile`, `obs`). A aparência avançada existente é **preservada**;
para modificá-la, use o botão **Editor avançado de aparência**.

## Fluxo seguro

1. Selecione a tecla e revise o perfil exibido no cabeçalho das propriedades.
2. Edite os campos. **Pré-visualizar (local)** não modifica o dispositivo.
3. Clique em **Salvar YAML com backup**; gravação apenas após validação YAML,
   hash do original e verificação de concorrência.
4. Clique em **Aplicar ao dispositivo (IPC)**; o serviço recarrega os perfis
   sem fechar a sessão HID.
5. O quadro é atualizado pelo espelho dos LCDs e pelo polling IPC.

Se houver edição não salva, a seleção de outra tecla será recusada até salvar
ou clicar em **Descartar edição / recarregar**.

**Sem ação** remove a definição da tecla ao salvar. Para controles completos
de imagem, posição e aparência, continue usando o editor avançado.

Não gravar credenciais OBS ou outros segredos em ações e YAML. As credenciais
WebSocket continuam em `~/.config/vision02/obs.json`.
