# Brilho global dos LCDs — Rise Mode Vision02

A captura USB do aplicativo oficial Windows contém o relatório de 512 bytes com
`CRT\x00\x00LIG\x00\x00\x64` (100%). A inicialização Linux da v15 já
utilizava `LIG 25`. O dispositivo usa **um único nível de brilho para os 15
LCDs**; não há evidência de ajuste individual por tecla.

## Uso

O serviço `vision02.service` é o único dono do dispositivo USB. Com ele ativo:

```bash
.venv/bin/python -m vision02.cli control brightness
.venv/bin/python -m vision02.cli control brightness 60
.venv/bin/python -m vision02.cli control status
```

No Studio, abra **Configurações → Brilho das teclas LCD (global)**, selecione
um valor entre 0 e 100% e clique em **Aplicar brilho**. O comando passa pelo
socket Unix privado da sessão HID (sem abrir `/dev/hidraw` uma segunda vez).

A preferência é guardada em `~/.config/vision02/brightness.json` (ou sob
`XDG_CONFIG_HOME`) com permissão `0600`. O serviço restaura o nível durante
cada inicialização ou reconexão; se não existir preferência, mantém 25%.
A alteração usa apenas `LIG`, sem `CLE`, `BAT`, `STP` ou gravação de firmware.

## Validação física pendente

Os novos valores intermediários (ex.: 60%) ainda precisam de confirmação visual
no Vision02 `0a00:1000` revisão `0300`. Teste 60 e retorne a 25 se desejar.
Quando `0%` for selecionado os LCDs podem apagar; restaure pelo comando CLI
`control brightness 25` sem precisar visualizar as teclas.

Não edite os YAML dos perfis. O comando não modifica ícones, cache de JPEGs,
menu de perfis ou configuração OBS.
