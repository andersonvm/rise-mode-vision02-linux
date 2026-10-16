# Vision 02 Studio — correção da superfície de composição

A prévia de composição agora utiliza um `Gtk.Picture` dentro de um `Gtk.Overlay`. Uma camada `Gtk.DrawingArea` transparente desenha somente as guias; o PNG é exibido pelo GTK nativamente.

Ao selecionar uma tecla, o Studio solicita automaticamente a prévia local e a mostra na área ampliada. Enquanto ela é produzida, pode ser exibida a imagem já publicada pelo serviço via IPC.

O arrasto na área com borda azul ativa **Usar aparência personalizada** caso ainda esteja desmarcado, exibe X/Y em tempo real e atualiza a prévia local com debounce. Nenhuma edição é gravada automaticamente: `Salvar YAML com backup` e `Aplicar ao dispositivo (IPC)` permanecem operações distintas.

A alteração afeta somente a GUI, sua documentação e os testes. O renderizador, a conexão HID e o serviço systemd não são modificados. Os testes automatizados não substituem a validação visual GTK no Ubuntu.
