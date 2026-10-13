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

## Concorrência e ciclo de vida HID

`read_event()` e `set_image()` podem executar em threads distintas. Cada operação
reserva a sessão por uma contagem protegida por `Condition`; o bloqueio da condição
é liberado antes do I/O. Operações aninhadas na mesma thread compartilham a reserva.
`_write_lock` serializa a sequência inteira BAT + JPEG + STP e a inicialização,
incluindo os intervalos originais. Protocolo e parâmetros JPEG permanecem iguais.

A ordem dos bloqueios é: ciclo de vida → condição, nas transições; reserva sob a
condição (liberada imediatamente) → escrita, nas transmissões. Quem mantém o
bloqueio de escrita pode adquirir brevemente a condição para consultar/registrar
falhas ou liberar reservas. Nenhum caminho mantém a condição enquanto espera pelo
bloqueio de escrita. `Condition.wait()` libera a condição enquanto aguarda operações.
Chamadas de ciclo de vida dentro de uma operação da mesma thread são rejeitadas.

`open()`, `close()` e `reconnect()` são serializados pelo bloqueio de ciclo de vida.
Uma transição fecha a admissão antes de esperar as operações já admitidas; novas
leituras/escritas recebem `RuntimeError` durante essa janela. Escritores já
admitidos terminam em ordem serializada antes do fechamento. Isso evita starvation
por uma thread de leitura contínua. A inicialização é exclusiva e somente a thread
da transição pode usar a sessão até que ela esteja pronta; falhas, inclusive
`KeyboardInterrupt`, liberam o descritor recém-aberto.

Leituras usam fatias de `select()` de até 50 ms e retornam `None` ao observar uma
transição. Uma leitura já pronta pode consumir seu relatório antes de liberar a
reserva; o descritor continua válido. `run()` propaga erros da sessão; ao encerrar
uma aplicação, sinalize seu `stop_event` e aguarde a thread para evitar uma nova
chamada após `close()`. Callbacks são executados fora das reservas HID.

Erros de transporte invalidam a sessão sem repetir relatórios. Transmissões
interrompidas também invalidam a sessão, pois podem estar incompletas. Operações
já em andamento podem concluir uma chamada de sistema concorrente com a falha;
novas operações e relatórios seguintes são bloqueados. `faulted` e `last_error`
ficam disponíveis; somente a abertura bem-sucedida de uma nova sessão limpa esses
campos. A recuperação continua explícita por `reconnect()`.

O encerramento aguarda a transmissão completa e os atrasos configurados. Escritas
não bloqueantes preservam o timeout de 2 s por relatório. Não há prazo global de
fechamento: codificação lenta, atrasos personalizados, escalonamento ou uma chamada
travada no kernel podem prolongá-lo. O driver não fecha um descritor ainda em uso
para tentar interromper I/O. Uma interrupção na espera do fechamento libera o
estado de transição; o chamador deve repetir `close()` após as operações terminarem.

Teste manual (acessa o hardware; requer `~/Imagens/terminal.png`):

```bash
.venv/bin/python teste_concorrencia_hid_v2.py
```

Compare as esperas RX com o timeout solicitado de 50 ms enquanto os displays
11–13 são atualizados. Os testes automatizados usam somente mocks, sem USB real.
