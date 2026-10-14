# Ações da Vision 02

Este incremento adiciona os tipos `script` e `hotkey` sem alterar o transporte HID.
Os tipos preexistentes `command`, `url` e `profile` continuam disponíveis.

## Executar scripts

```yaml
action:
  type: script
  path: ../scripts/vision02-aviso.sh
  interpreter: bash
  args: ['Olá do teclado']
```

O campo `path` é relativo ao arquivo YAML (ou absoluto). O arquivo deve existir
no momento da validação e da execução. Os intérpretes permitidos são `bash` e
`python3`. Para `python3`, utiliza-se o mesmo Python da aplicação (`sys.executable`).
O script é iniciado sem shell intermediário (`shell=False`). Por padrão, a ação
não aguarda o término do processo: sucesso significa **processo iniciado**, não
execução concluída. Saída padrão e erros do processo filho são descartados,
seguindo o comportamento das ações `command` já existentes.

## Atalhos de teclado

```yaml
action:
  type: hotkey
  keys: [ctrl, shift, t]
```

Em **X11**, requer `xdotool` e uma janela apropriada em foco. Para instalar
no Ubuntu: `sudo apt install xdotool`. Em **GNOME Wayland**, veja a seção abaixo.

## Atalhos no GNOME Wayland

No Ubuntu com GNOME Wayland, os atalhos usam `org.freedesktop.portal.RemoteDesktop`
via `dbus-next`. Instale: `python -m pip install -e '.[wayland]'`.

Na primeira utilização de `hotkey`, o GNOME **solicita autorização explícita**.
Aguarde a autorização e selecione a janela de destino durante os 4 segundos
apresentados no terminal. O atalho é enviado à janela que estiver em foco.
Permissões não são persistidas entre execuções (`persist_mode=0`). Durante a
execução, a mesma sessão D-Bus é reutilizada para todos os atalhos. A sessão
é encerrada quando `vision02 profile run` termina.

A versão inicial reconhece `ctrl`, `shift`, `alt`, `super`, `meta`, letras,
números, `F1`–`F12`, `enter`, `tab`, `esc`, `backspace`, setas, `home`, `end`,
`pageup`, `pagedown`, `insert`, `delete` e `space`. Outros nomes retornam
um erro claro, sem produzir sequências de teclado arbitrárias.

Em X11, o backend `xdotool` continua disponível.

## Segurança e operação

- Carregue apenas YAML e scripts de fontes confiáveis: a tecla executa ações com
  os privilégios do usuário que iniciou o processo.
- Comandos e scripts são iniciados com `shell=False`; nunca concatenamos comandos
  recebidos do YAML numa linha de shell.
- O controlador já possui fila e thread próprias; operações de scripts não devem
  bloquear a thread que lê os eventos USB.
- Falhas ao iniciar ações são registradas pelo controlador; não encerram a fila.
- `examples/profiles/acoes-exemplo.yaml` é um perfil independente, que pode ser
  validado sem abrir o dispositivo: `vision02 profile validate examples/profiles/acoes-exemplo.yaml`.
- **Não** execute automaticamente o perfil de exemplo se não desejar que as teclas
  abram aplicativos, URLs ou atalhos reais.
