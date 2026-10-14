# Controle local da Vision 02

A Vision 02 continua sendo controlada por **um único processo** (`vision02 profile run`),
executado pelo supervisor `vision02.hotplug` via `systemd --user`.

O controlador publica um socket Unix privado em
`$XDG_RUNTIME_DIR/vision02/control.sock` quando o dispositivo está conectado
e os displays já foram inicializados. A GUI futura e a CLI acessam a mesma API;
**nenhum cliente deve abrir `/dev/hidraw*`**.

## Comandos

```bash
.venv/bin/vision02 control status
.venv/bin/vision02 control profiles
.venv/bin/vision02 control switch Observabilidade
.venv/bin/vision02 control switch Desenvolvimento
```

As respostas são objetos JSON com `ok: true` ou `ok: false`.
`switch` só aceita um perfil que já foi carregado no serviço. Não há
execução de comandos arbitrários nem gravação de YAML por IPC nesta etapa.

## Segurança e concorrência

- Socket criado dentro do diretório temporário do usuário (não fica no repositório).
- Diretório com permissão `0700`, socket e lock com `0600`.
- `SO_PEERCRED` confirma que os clientes usam o mesmo UID no Linux.
- A trava `flock` impede dois servidores IPC no mesmo caminho.
- Os comandos são enviados a uma **fila** e executados pela thread que controla HID,
  antes da próxima chamada a `read_event()`: não há escrita USB concorrente.
- O servidor pode responder com erro se o dispositivo estiver ausente, se uma
  troca falhar ou se o controlador estiver encerrando.
- O protocolo possui limite de tamanho, timeouts e não expõe uma operação de
  execução de shell.

## Ativação no serviço

O supervisor passa `--ipc` ao processo filho automaticamente. Não é necessário
editar a unidade `systemd` existente.

Após atualizar o código e executar os testes:

```bash
systemctl --user restart vision02.service
.venv/bin/vision02 control status
.venv/bin/vision02 control profiles
.venv/bin/vision02 control switch Observabilidade
.venv/bin/vision02 control switch Desenvolvimento
```

Para observar os eventos e erros:

```bash
journalctl --user -u vision02.service -f
```

Enquanto o serviço estiver ativo, evite executar outro `vision02 profile run`.
Se precisar iniciar o perfil manualmente para depuração, pare antes o serviço;
use `vision02 profile run ... --ipc` para habilitar o socket nesse modo.

**Limitações atuais:** a lista de perfis é a carregada no início do processo.
Após hotplug, o processo é recriado e volta ao perfil Desenvolvimento. A edição
persistente de YAML, o salvamento do perfil ativo e a interface GTK ficam para
etapas posteriores.
