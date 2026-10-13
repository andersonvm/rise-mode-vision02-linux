# Rise Mode Vision 02 — controlador experimental para Linux

Controlador em Python para o HID `0a00:1000`, derivado de testes com o equipamento. **Não é software oficial.** Testado experimentalmente no Ubuntu; reconexão automática, confirmação por LCD e operação prolongada ainda não estão implementadas.

## Instalação em ambiente virtual

Desconecte a controladora USB do VirtualBox e confirme que o driver em uso é `usbhid`.

```bash
cd rise-mode-vision02-linux
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

## Comandos

```bash
.venv/bin/vision02 discover
.venv/bin/vision02 mapping
.venv/bin/vision02 listen
.venv/bin/vision02 number
.venv/bin/vision02 image 11 /caminho/para/imagem.png
```

`number` atualiza todos os 15 LCDs, substituindo o conteúdo atual. `image` modifica um único LCD. Os comandos de saída inicializam a controladora com `DIS, LIG, QUCMD, LIG`, usam `BAT` + JPEG, rotação de 180° e `STP` por imagem com pausas de 5 ms/100 ms, conforme testes. A escrita aceita pelo Linux não garante renderização perfeita: a tela 12 precisou de retransmissão em um dos experimentos.

## Endereçamento físico dos LCDs

De frente para o equipamento:

```text
11 12 13 14 15
06 07 08 09 10
01 02 03 04 05
```

Os eventos `ACK..OK` de teclas foram capturados como IDs 1–15 na sequência física superior para inferior. `physical_key_to_display_id` converte assumindo esta ordem (verifique na sua configuração).

## API

```python
from vision02 import Vision02

with Vision02() as controller:
    controller.set_image(11, "terminal.png")
    controller.set_image_for_key(1, "terminal.png")  # corresponde ao LCD 11
    controller.on_press(1, lambda key: print(key))
    controller.run()
```

## Limites

- Requer Linux com interface `hidraw`, sem controle concorrente pelo VirtualBox.
- Descoberta por `HID_ID` em sysfs, dispensando o número fixo `/dev/hidraw4`.
- Não inclui interface gráfica, reconexão automática, atalhos do sistema ou política de retry cega.
- Prefira executar como usuário normal se as permissões `udev` o permitirem.
- O estado da tela é verificado visualmente: não foi identificado ACK de conclusão de cada JPEG.
