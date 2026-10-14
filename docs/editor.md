# Editor visual de teclas — Vision 02

A janela de edição usa o GTK 4/libadwaita do Python do sistema. O backend YAML
usa `.venv/bin/python`, Pillow e PyYAML. Nenhum dos dois abre USB/HID.

Execute `./scripts/vision02-editor` ou clique em **Editar teclas** no painel.

## Processo

1. Selecione Desenvolvimento ou Observabilidade para editar.
2. Clique na tecla **física** de 01 a 15, altere imagem, rótulo ou ação.
3. Use **Pré-visualizar** para testar a renderização em memória e em cache, sem
   sobrescrever o YAML.
4. **Salvar YAML** valida a configuração por meio do loader oficial, mantém
   um backup em `~/.local/state/vision02/editor-backups/` e substitui o YAML de
   maneira atômica. O editor rejeita gravações se outra ferramenta alterou
   o arquivo desde a abertura.
5. **Reiniciar serviço para aplicar** só é habilitado após salvar e pede uma
   confirmação. Ele executa `systemctl --user restart vision02.service` e
   reinicia o dispositivo no perfil Desenvolvimento. Se não quiser reiniciar,
   feche o editor; o YAML continuará salvo.

Ações: `command` (linha interpretada com `shlex`, *sem shell*), `url`, `script`
(bash/Python), `hotkey` e `profile`. Escolher **Sem ação** remove a configuração
da tecla. A tecla pode permanecer com um caminho de imagem absoluto ou relativo
ao diretório do perfil. O editor trabalha inicialmente com os dois perfis em
`examples/profiles` utilizados pelo serviço.

**Observação:** o salvamento com PyYAML normaliza a formatação e pode remover
comentários existentes. O conteúdo anterior é preservado no backup. Para a
edição de outras coleções de perfis e atualização sem reinício, ampliaremos a
API IPC em outra etapa.

Evite executar `vision02 profile run` manualmente enquanto `vision02.service`
estiver ativo.
