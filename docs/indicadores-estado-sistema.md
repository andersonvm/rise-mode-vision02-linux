# Indicadores operacionais da Vision 02 (Ubuntu/GNOME)

## Objetivo

Exibir nos LCDs **estados reais** de áudio, microfone, Wi-Fi e Bluetooth ao
lado das métricas CPU/RAM/GPU/DISCO/REDE do dashboard existente. Não modifica
perfis, ações, atalhos ou imagens pessoais. Só atua no perfil **Sistema**.

## Mapeamento automático

O módulo reconhece os rótulos abaixo **somente nas teclas físicas 06 a 14**:

| Rótulos aceitos | Estado mostrado | Origem | Observação |
|---|---|---|---|
| `MUDO`, `AUDIO MUDO`, `ÁUDIO MUDO` | `ATIVO` / `MUDO` | `wpctl`, fallback `pactl` | Mudo inclui a situação em que o volume é zero **apenas** se o dispositivo reportar mute; 0% sem mute permanece ATIVO. |
| `MIC MUDO`, `MICROFONE MUDO` | `ATIVO` / `MUDO` | `wpctl`, fallback `pactl` | Usa entrada de áudio padrão PipeWire/PulseAudio. |
| `WIFI`, `WI-FI` | `CONECTADO` / `SEM REDE` / `DESLIGADO` | `nmcli` | Diferencia rádio ligado sem associação de rádio desligado. |
| `BLUETOOTH`, `BT` | `LIGADO` / `DESLIGADO` | `/sys/class/rfkill` | Reflete estado do rádio; **não** indica dispositivo Bluetooth conectado. |

**Tecla física 15**: preservada para navegar entre perfis. Os rótulos atuais
do pacote Sistema usam as teclas 08 (`MUDO`), 09 (`MIC MUDO`) e 10 (`WIFI`).
O Bluetooth não é automaticamente adicionado ao YAML: utilize o editor para
atribuir o rótulo `BLUETOOTH` a alguma tecla 06–14, se desejar.

Teclas com o bloco opcional `appearance` configurado **não são substituídas**:
a imagem personalizada vence a atualização automática. Outros perfis nunca
são atualizados. **As ações das teclas não são alteradas.** Um estado mostrado
no LCD não cria uma ação de ativar/desativar o recurso.

## Intervalos e arquitetura

Uma thread separada consulta fontes **somente de leitura** a cada 3 segundos.
O dashboard existente continua coletando métricas a cada 8 segundos.
Ambos publicam snapshots imutáveis; **somente o loop proprietário HID** chama
`device.set_image()`, com no máximo **uma imagem por passagem** e intervalo
global mínimo de 200 ms. As filas são intercaladas para não bloquear o
monitoramento de métricas.

Se a fonte não estiver disponível, exibe `N/D` (não presume DESLIGADO).
Comandos de consulta têm timeout de 1 segundo e não usam `sudo`. Se uma
transmissão HID falhar, a exceção segue o fluxo existente para recuperação
pelo supervisor USB.

## Ativação

Após instalar código, confirme aprovação dos testes e reinicie **uma vez**:

```bash
systemctl --user restart vision02.service
.venv/bin/vision02 control switch Sistema
.venv/bin/vision02 control status
```

No perfil Sistema, faça testes reversíveis:

1. Silencie/reative o microfone pelo GNOME e aguarde até 3–5 segundos.
2. Silencie/reative o áudio e confira a tecla 08.
3. Observe o Wi-Fi. **Não o desligue se essa for sua conexão remota.**
4. Se configurou uma tecla Bluetooth, use as Configurações do GNOME para
   alterar o estado e conferir a atualização.
5. Troque para Observabilidade e de volta para Sistema; não devem restar
   imagens de estados do perfil anterior.

O PID do serviço não deve mudar apenas por alterações de áudio/rede:

```bash
systemctl --user show -p MainPID vision02.service
journalctl --user -u vision02.service -n 30 --no-pager
```

## Diagnóstico rápido

```bash
wpctl get-volume @DEFAULT_AUDIO_SINK@
wpctl get-volume @DEFAULT_AUDIO_SOURCE@
nmcli radio wifi
nmcli -t -f TYPE,STATE device status
find /sys/class/rfkill -maxdepth 2 -name type -print
```

Não é necessária integração com OBS Studio nesta etapa. Esse recurso pode
ser desenvolvido separadamente via OBS WebSocket.
