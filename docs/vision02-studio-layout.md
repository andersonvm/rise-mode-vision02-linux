# Navegação redimensionável — Vision 02 Studio

A barra lateral foi convertida de um `Gtk.Box` com largura fixa para um
`Gtk.Paned` horizontal. Arraste a divisória vertical entre **VISION 02** e o
conteúdo para ajustar a largura da navegação. As sete seções são:
Dashboard, Teclas, Perfis, Ícones, Sistema, OBS Studio e Configurações.

O painel lateral ocupa a altura disponível; seu conteúdo pode rolar quando
necessário. A largura inicial é 265 px, com intervalo de 230 a 480 px.
A preferência é salva após o arraste em
`~/.config/vision02/studio-ui.json`, ou no diretório de `XDG_CONFIG_HOME`.

A preferência visual não afeta `settings.json`, perfis YAML, OBS, IPC ou HID.
Se necessário, feche o Studio e apague apenas `studio-ui.json` para restaurar
a largura padrão.

O serviço `vision02.service` não precisa ser reiniciado. Basta fechar e abrir
a janela `./scripts/vision02-studio` após instalar a correção.
