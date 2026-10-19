# Vision 02 Studio — correção da grade compacta (v14.1)

Esta atualização corrige o dimensionamento real da grade 5 × 3 da v14.
Os `Gtk.Button` antes eram distribuídos pelo `Gtk.Grid` quando o
`Gtk.Paned` cedia espaço adicional; `set_size_request()` era apenas o
**tamanho mínimo**. Como resultado, os cartões ficavam muito maiores
que o display e ocupavam o painel inteiro. A implementação agora usa
`Gtk.Fixed` com as 15 posições calculadas por `deck_key_position()`:

- 5 colunas × 3 linhas; botões de 106 × 116 pixels lógicos;
- ícones LCD de 86 × 86; 11 pixels de distância entre botões;
- superfície de 574 × 370, cercada por moldura de equipamento;
- contêiner centralizado horizontal e verticalmente;
- largura inicial do painel de teclas migrada para no mínimo 660;
- estado de seleção preservado pela borda azul, sem legenda longa
  capaz de aumentar a largura natural de uma tecla;
- janela inicia **maximizada**, mas não em modo tela cheia: barra do
  GNOME, redimensionamento e restauração manual continuam disponíveis.

## Instalação

Pelo menu do Ubuntu, abra **Vision 02 — Atualizações**, selecione
`vision02-layout-compacto-v14-1-update.zip`, **Inspecionar atualização** e
**Aplicar e testar**. Requer a versão v14 instalada; o gerenciador exige
SHA-256 exato dos arquivos de origem. O pacote possui seis arquivos:
Studio, módulo de layout, dois testes existentes atualizados,
uma nova suíte de testes e esta documentação.

Feche e reabra o Studio. Em **Teclas**, verifique 15 botões de tamanho
uniforme em uma grade 5 × 3 centralizada, mesmo com o aplicativo
maximizado. Verifique seleção e destaques de teclas pressionadas.
A janela abrirá maximizada; use o botão de restauração do GNOME
caso deseje utilizá-la em tamanho menor. Em telas realmente pequenas,
a grade poderá requerer rolagem horizontal em vez de distorcer botões.

Não altera o controlador, USB/HID, serviços, os YAML pessoais,
credenciais OBS, imagens de teclas nem o funcionamento do IPC.

## Testes

Regressão com `python -m pytest -q`; teste visual de GTK4/Wayland
continua necessário na máquina do usuário. O gerenciador cria backup
antes da instalação e restaura os arquivos se a validação falhar.
