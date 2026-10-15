# Integração OBS WebSocket 5.x — Vision 02

- Suportada na versão OBS Studio 32.2.0 e obs-websocket 5.x.
- O serviço Vision 02 conecta **somente a localhost** por TCP/WebSocket JSON. A conexão **não usa TLS**, pois não sai do host. No OBS, prefira vincular o servidor somente a 127.0.0.1 em vez de 0.0.0.0.
- No OBS: **Ferramentas → Configurações do servidor WebSocket**, habilite WebSocket, autenticação e uma senha forte. Porta padrão 4455.
- A senha não deve ser colocada nos YAML dos perfis, no Git, em comandos de terminal ou nos logs. Use o assistente `python ~/Downloads/instalar_obs_vision02.py --configure` (digita a senha sem eco). A configuração fica em `~/.config/vision02/obs.json` com permissões 0600, exclusivamente do usuário.
- Execute `./scripts/vision02-obs-test` para validar autenticação sem abrir USB/HID e sem iniciar comandos do OBS.
- O worker `OBSWorker` é o único cliente da API OBS. O controlador de teclas entrega as ações a uma fila; a thread responsável pelo HID permanece exclusiva. Se o OBS estiver offline, a ação é rejeitada, **não é repetida após a reconexão**.
- O usuário deve manter ativado o servidor WebSocket ao utilizar o perfil **OBS Studio**. Sem OBS em execução, os indicadores exibem `OFFLINE`, mas outras teclas e perfis permanecem operacionais.
- Ao alterar credenciais, reinicie apenas uma vez `vision02.service` para o worker ler `obs.json` novamente. A troca de perfis continua dinâmica via IPC.

## Operações YAML

`type: obs`, `operation:` uma de:

| Operação | OBS Request |
|---|---|
| `toggle_record` | `ToggleRecord` |
| `toggle_pause` | `PauseRecord` / `ResumeRecord` |
| `toggle_stream` | `ToggleStream` |
| `toggle_mic` / `toggle_desktop` | `ToggleInputMute` |
| `scene_slot` com `slot: 1`, `2`, `3` | `SetCurrentProgramScene`, cena na posição do resultado `GetSceneList` |
| `next_scene`, `previous_scene` | `GetSceneList` + `SetCurrentProgramScene` |
| `toggle_virtualcam` | `ToggleVirtualCam` |
| `save_replay` | `SaveReplayBuffer` (buffer deve estar iniciado no OBS) |
| `screenshot` | `SaveSourceScreenshot` para `~/Pictures/Vision02-OBS/` |
| `refresh` | atualiza indicadores, sem modificar o OBS |

Os nomes das cenas são descobertos; não são presumidos. Para entradas de áudio, são usados os campos `mic1` e `desktop1` de `GetSpecialInputs`. Se não existirem, informe `mic_input` e `desktop_input` em `obs.json` ou `input: NOME` no YAML da tecla. No gerenciador GTK, selecione `OBS WebSocket` e informe a operação.

Exemplo:

```yaml
version: 1
name: OBS Studio
keys:
  1:
    label: Gravação
    action: {type: obs, operation: toggle_record}
  6:
    label: Cena 1
    action: {type: obs, operation: scene_slot, slot: 1}
  15:
    label: Sistema
    action: {type: profile, target: Sistema}
```

## Indicadores

No perfil **OBS Studio**, as teclas 01–14 que possuam uma ação OBS e **não** possuam `appearance` personalizada recebem imagens dinâmicas; tecla 15 permanece o ícone Voltar. Todas as imagens são RGB 100×100. Os estados são consultados aproximadamente a cada três segundos; o scheduler HID envia uma imagem por iteração e respeita o intervalo global de 200 ms. O controlador também preserva a capacidade de trocar perfis por IPC e o mecanismo de reconexão USB.

Na primeira execução, use um perfil com a gravação/transmissão PARADA para evitar efeitos inesperados ao pressionar uma tecla. Iniciar transmissão é uma operação real no OBS e poderá iniciar uma live.

## Diagnóstico

```bash
./scripts/vision02-obs-test
.venv/bin/python -m pytest -q
systemctl --user restart vision02.service
.venv/bin/vision02 control reload
.venv/bin/vision02 control switch 'OBS Studio'
journalctl --user -u vision02.service -n 60 --no-pager
```

Para manter sua configuração de áudio no OBS Linux, edite `~/.config/vision02/obs.json` com o editor de sua preferência e preserve `chmod 600`. Nunca cole o conteúdo desse arquivo em chats ou issues.
