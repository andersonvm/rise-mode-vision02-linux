# Alça de redimensionamento — correção GTK

A Composição V2 desenhava um quadrado de 14 px na camada Cairo do
`Gtk.DrawingArea`, que pode não aparecer sobre o `Gtk.Picture` na sessão GTK.
Além disso, o quadrado ficava junto à borda inferior direita, dificultando
localizá-lo e receber o primeiro clique.

O Studio agora usa um `Gtk.Frame` de 40 × 40 px, com fundo azul, borda branca,
seta **↘** e dica de ferramenta. Ele é acrescentado como último filho de
`Gtk.Overlay`, por cima da imagem. Um `Gtk.GestureDrag` exclusivo da alça
aciona redimensionamento independentemente do hit-test do Cairo. Arrastar o
restante da imagem continua movendo a posição X/Y. O controle é escondido
quando a seleção muda para Texto ou não há tecla carregada.

A alça não integra o PNG da pré-visualização ou o JPEG enviado ao LCD.
As ações de Desfazer/Refazer, limites de escala (25% a 200%) e salvamento
YAML/IPC são mantidas sem alteração. Não há mudanças no serviço USB/HID.

## Validação manual no Ubuntu

1. Feche e reabra `./scripts/vision02-studio` após a instalação.
2. Entre em Teclas → Composição, selecione Imagem na tecla VS Code.
3. Identifique a **alça azul 40 × 40 com seta ↘** no canto inferior direito.
4. Arraste a alça para dentro e para fora. Observe `Imagem: tamanho (%)`.
5. Clique em Desfazer e Refazer; mude para Texto (alça deve sumir).
6. Faça uma edição pequena e confira Pré-visualizar, Salvar YAML e Aplicar IPC.

O teste automatizado valida a construção e callbacks por inspeção de código e
execução isolada. A interação visual GTK precisa de validação em desktop real.
