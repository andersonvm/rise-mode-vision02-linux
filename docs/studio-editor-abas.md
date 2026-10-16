# Vision 02 Studio — editor de propriedades por abas

A seção **Teclas** mantém a grade física 5 × 3 à esquerda. À direita, um
`Gtk.Notebook` possui quatro páginas, cada uma com rolagem independente:

- **Ação:** tipo, parâmetros, comandos, URL, script, atalho e OBS.
- **Imagem:** caminho, biblioteca visual, pesquisa, importação e miniatura.
- **Texto:** rótulo, texto exibido, fonte, cores e alinhamento.
- **Composição:** enquadramento, posições X/Y, escala, prévia arrastável, zoom,
  alça de redimensionamento, guias e desfazer/refazer.

A caixa **Usar aparência personalizada** fica acima das abas e controla os
campos de Texto e Composição. As abas consultam os mesmos widgets e o mesmo
estado de edição. Trocar de aba **não salva, aplica ou descarta** alterações.

A barra inferior permanece visível: estado da edição, prévia local,
**Salvar YAML com backup**, **Aplicar ao dispositivo (IPC)**,
**Descartar/recarregar** e editor avançado. A aplicação ao hardware só acontece
após salvamento explícito, utilizando o IPC existente.

A divisória horizontal entre grade e propriedades pode ser arrastada e sua
posição é preservada em `~/.config/vision02/studio-editor-layout.json`
(ou em `$XDG_CONFIG_HOME/vision02/studio-editor-layout.json`). Essa preferência
não é incluída no Git, não contém dados de perfil e usa permissões `0600`.

## Teste manual no Ubuntu

1. Abra `./scripts/vision02-studio` e vá a **Teclas**.
2. Selecione uma tecla e modifique um campo em **Texto** sem salvar.
3. Mude para **Imagem**, depois **Ação** e volte a **Texto**: a edição
   deve permanecer e o botão **Aplicar IPC** não deve ficar habilitado.
4. Confira a biblioteca na aba Imagem e a prévia com alça na aba Composição.
5. Arraste a divisória central, feche e reabra o Studio; confira a largura.
6. Salve o YAML com backup e aplique por IPC, confirmando a imagem no LCD.
7. Em caso de alteração não salva, o Studio deve impedir o fechamento sem
   salvar ou descartar, como na versão anterior.

O controlador HID, os perfis e as credenciais OBS não são modificados pela
instalação desta interface. Nenhuma tecla da interface executa ações físicas.
