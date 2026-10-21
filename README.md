# Rise Mode Vision 02 Linux — Studio GTK4 e controlador USB/HID

**Projeto independente de software oficial** para controlar e personalizar o **Rise Mode Vision 02** no Linux, com **15 teclas programáveis e displays LCD individuais**. Desenvolvido e testado no Ubuntu, integra um controlador USB/HID em Python, serviço de supervisão, perfis YAML, ações, integração OBS Studio e uma interface gráfica **Vision 02 Studio** baseada em GTK4/libadwaita.

## Instalação por pacote Debian (Ubuntu 24.04+)

**[Baixar a última versão estável (.deb) — GitHub Releases](https://github.com/andersonvm/rise-mode-vision02-linux/releases/latest)**

Na página da versão, abra **Assets**, baixe o arquivo `vision02-studio-desktop_1.0.0-1_all.deb` (ou a versão mais recente) e instale com o gerenciador de pacotes do Ubuntu:

```bash
sudo apt install ./vision02-studio-desktop_*_all.deb
```

O pacote inclui o Studio e as bibliotecas do projeto, instala o atalho no menu do Ubuntu e resolve as dependências Python/GTK pelo `apt`. **Não ativa automaticamente o serviço HID**, não altera seus perfis pessoais e não substitui configurações OBS. Para operar os LCDs, configure o controlador com IPC; consulte o [guia de instalação Debian](docs/instalacao-deb.md).

> **Versão estável:** **v1.0.0**, primeira baseline funcional validada no Ubuntu. A numeração pública foi reiniciada; a release histórica `v15.0.0` permanece disponível. O pacote Python também utiliza `1.0.0` em `pyproject.toml`. Projeto comunitário, sem afiliação ao fabricante.

## O que já funciona

| Área | Funcionalidades |
| --- | --- |
| **Hardware USB/HID** | Detecção da Vision 02 (VID:PID `0a00:1000`) por sysfs/`hidraw`, leitura das 15 teclas, envio de imagens JPEG aos 15 LCDs e cache de imagens |
| **LCDs e brilho** | Inicialização em lote dos 15 LCDs sem bordas brancas; brilho global de 0% a 100% por CLI ou Studio, com persistência e restauração após reconexão. |
| **Ciclo de vida** | Sessão HID persistente, serialização de escrita, tratamento de falhas e supervisor de desconexão/reconexão com espera progressiva |
| **Vision 02 Studio** | Interface GTK4/libadwaita com painel de controle, edição visual de teclas, perfis, ícones, estado do sistema e integração OBS |
| **Editor visual** | Grade física **5 × 3 compacta**, seleção de teclas, abas **Ação / Imagem / Texto / Composição**, pré-visualização, salvamento com backup e aplicação via IPC |
| **Imagens e presets** | Galeria de **90 miniaturas**, janela de galeria ampliada, importação de ícones, composição visual com camadas, posicionamento, escala e editor interativo de presets |
| **Perfis** | Perfis YAML, criação/duplicação/renomeação, troca pelo equipamento ou IPC, catálogo dinâmico, recarregamento sem reiniciar o controlador e persistência do último perfil |
| **Menu de Perfis (Studio v15)** | Seleção de perfis diretamente nos LCDs; **tecla física 15** retorna ao menu; até 14 perfis por página, com paginação, backup e restauração |
| **Ações** | Comandos, URLs, scripts, atalhos de teclado, troca de perfis e operações de OBS WebSocket |
| **OBS Studio** | Cenas, gravação, transmissão, áudio, câmera virtual, buffer de replay e indicadores de estado, com autenticação configurada fora do Git |

### Interface do equipamento

A interface **Teclas** mostra os 15 botões agrupados em cinco colunas e três linhas, com tamanho fixo e centralização. O Studio abre maximizado, mantendo os controles de janela do ambiente gráfico. No painel direito, a galeria de miniaturas possui rolagem própria e pode ser aberta em uma janela maior.

As alterações na interface **não** acionam automaticamente o hardware. Inspecionar, pré-visualizar, salvar o YAML e **Aplicar ao dispositivo (IPC)** são operações distintas.

## Arquitetura

```text
┌───────────────────────────────────────────────┐
│ Vision 02 Studio (GTK4 / libadwaita)          │
│ Teclas · Perfis · Menu de Perfis · Ícones     │
│ OBS Studio · Sistema · Configurações          │
└──────────────────────┬────────────────────────┘
                       │ backend / socket IPC local
                       ▼
          Serviço controlador Vision 02
          Python · perfis YAML · fila de ações
                       │
           Supervisor hotplug (systemd --user)
                       │
                       ▼
              Linux hidraw / USB HID
                       │
                       ▼
             Rise Mode Vision 02
             15 teclas / 15 LCDs
```

O **processo controlador é o único proprietário do USB/HID**. O Studio e os clientes da CLI utilizam o socket IPC local para consultar o estado, trocar perfis, recarregar o catálogo e aplicar alterações. Isso evita conexões HID concorrentes entre a GUI e o serviço.

O supervisor em `src/vision02/hotplug.py` detecta a conexão e a desconexão e reinicia o controlador quando necessário. Ele não repete indiscriminadamente transmissões JPEG com falha.

## Requisitos

- Linux com interface `hidraw` e dispositivo Rise Mode Vision 02 (`0a00:1000`);
- Python **3.10+**;
- GTK4, libadwaita e PyGObject para as interfaces gráficas;
- Pillow e PyYAML para perfis e imagens;
- Sessão gráfica GNOME/Wayland ou ambiente GTK compatível;
- Acesso ao `/dev/hidraw*` do dispositivo por permissões de usuário/`udev`.

**Importante:** o dispositivo não pode estar sob controle simultâneo do VirtualBox, de outra máquina virtual ou de outro processo que tente utilizar o HID.

## Instalação a partir do código-fonte (Ubuntu)

Instale as dependências do sistema:

```bash
sudo apt update
sudo apt install -y \
  git python3 python3-venv python3-pip \
  python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

Clone o projeto e prepare o ambiente virtual:

```bash
git clone https://github.com/andersonvm/rise-mode-vision02-linux.git
cd rise-mode-vision02-linux

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,wayland]'
```

O script do Studio usa `/usr/bin/python3` para acessar o GTK instalado pelo sistema, enquanto o backend utiliza a `.venv` para as dependências Python. **Mantenha os dois ambientes disponíveis.**

### Abrir o Vision 02 Studio

```bash
./scripts/vision02-studio
```

Outras ferramentas gráficas presentes no repositório:

```bash
./scripts/vision02-profiles     # Gerenciador de perfis
./scripts/vision02-editor      # Editor de teclas
./scripts/vision02-gui         # Painel gráfico
./scripts/vision02-obs-panel   # Painel OBS
```

Os atalhos do menu de aplicativos do Ubuntu e o **Gerenciador de Atualizações** fazem parte de instaladores desktop distribuídos separadamente; **não são criados automaticamente** pelo comando `pip install -e .`.

### Serviço e conexão USB

O projeto possui exemplo de unidade em [`packaging/systemd/vision02.service`](packaging/systemd/vision02.service). Antes de ativá-la, **ajuste os caminhos de `WorkingDirectory` e `ExecStart`** para a instalação real e configure o carregamento do catálogo de perfis.

Se o serviço já estiver instalado:

```bash
systemctl --user status vision02.service
journalctl --user -u vision02.service -f
.venv/bin/vision02 control status
```

Não execute um segundo `vision02 profile run`, `vision02 listen` ou outro cliente que abra `hidraw` diretamente enquanto o serviço controla o dispositivo. Para depuração direta, interrompa primeiro o serviço.

Consulte [supervisão USB](docs/hotplug.md), [IPC](docs/ipc.md) e [gerenciamento de perfis](docs/gerenciamento-perfis.md).

## Como utilizar os perfis e o Menu de Perfis

Os perfis pessoais ficam em:

```text
~/.config/vision02/profiles/
```

No **Vision 02 Studio → Menu de Perfis**:

1. Clique em **Inspecionar catálogo** para ver os perfis disponíveis.
2. Revise a função atual da tecla 15 e confirme a substituição.
3. Clique em **Sincronizar menu e tecla 15**. O Studio cria backup antes de gravar os YAML.
4. Clique em **Recarregar catálogo (IPC)**.
5. Clique em **Abrir menu nos LCDs (IPC)** ou pressione a tecla 15 de um perfil.

Nos perfis comuns, a tecla 15 retorna ao **Menu de Perfis**. Dentro do menu, as teclas selecionam os perfis; quando houver mais de 14 opções, a tecla 15 controla a paginação. **Adicionar um novo perfil requer nova sincronização do menu** — a inclusão não ocorre automaticamente.

Backups do menu: `~/.local/state/vision02/menu-perfis-backups/`.

> A sincronização substitui a função anterior da tecla 15 nos perfis incluídos. As demais teclas são preservadas. Existe opção de restauração do último backup na interface.

Documentação: [Menu de Perfis v15](docs/studio-menu-perfis-v15.md).

### Perfil OpenBoard

O projeto inclui um exemplo completo para o **OpenBoard**, com YAML, script de abertura e **15 ícones PNG**:

- [Perfil YAML](examples/profiles/openboard.yaml)
- [Ícones](examples/profile-icons/openboard/)
- [Script de abertura](examples/profile-tools/launch-openboard.sh)
- [Manual do perfil](docs/perfil-openboard.md)

As teclas 1–14 fornecem funções como caneta, borracha, marca-texto, seleção, texto, desfazer/refazer e navegação. A **tecla 15** retorna ao Menu de Perfis. Os atalhos dependem da versão do OpenBoard e de a janela correta estar em foco.

**O arquivo de exemplo no Git não é instalado automaticamente no perfil pessoal.** Siga o [manual de instalação do OpenBoard](docs/perfil-openboard.md) e depois sincronize o Menu de Perfis no Studio para exibi-lo nos LCDs.

## CLI e IPC

Exemplos de comandos seguros para consultar a instância em execução:

```bash
.venv/bin/vision02 control status
.venv/bin/vision02 control profiles
.venv/bin/vision02 control switch 'OpenBoard'
.venv/bin/vision02 control reload
```

O comando `switch` exige que o perfil já tenha sido carregado no catálogo. `reload` valida e aplica as alterações sem abrir uma nova conexão USB.

Para inspecionar ou validar configurações:

```bash
.venv/bin/vision02 discover
.venv/bin/vision02 mapping
.venv/bin/vision02 profile validate examples/profiles/openboard.yaml
```

A API Python permanece disponível:

```python
from vision02 import Vision02

with Vision02() as controller:
    controller.set_image_for_key(1, "terminal.png")
    controller.on_press(1, lambda key: print(key))
    controller.run()
```

**Não use essa API de acesso direto em paralelo com o serviço ativo.**

## Ações, Wayland e OBS

Os perfis suportam ações `command`, `url`, `script`, `hotkey`, `profile` e `obs`.

- **GNOME Wayland:** atalhos utilizam o portal `org.freedesktop.portal.RemoteDesktop`; pode ser necessária autorização interativa. O extra `.[wayland]` instala `dbus-next`.
- **X11:** os atalhos podem utilizar `xdotool` (instalação à parte).
- **OBS WebSocket 5.x:** configure autenticação no OBS e armazene os dados localmente em `~/.config/vision02/obs.json`, com permissões restritas. **Nunca publique senhas no Git.**

Consulte [ações e atalhos](docs/acoes.md) e [integração OBS WebSocket](docs/integracao-obs-websocket.md).

## Testes

```bash
.venv/bin/python -m pytest -q
```

**Validação da baseline v1.0.0:** testes automatizados executados em uma árvore limpa do projeto; confira o resultado do CI da release para a contagem final.

Os testes automatizados cobrem lógica de perfis, interface, composição de imagens, comunicação simulada, sessão HID, concorrência e integração IPC. **Testes com mocks não substituem testes físicos nos 15 LCDs e na sessão gráfica do Ubuntu.**

## Organização do repositório

```text
apps/                   Aplicações GTK4 e backends
src/vision02/           Controlador, perfis, ações, IPC, OBS e Studio
scripts/                Launchers das interfaces e ferramentas
examples/profiles/      Exemplos de perfis YAML
examples/profile-icons/ Ícones de exemplos, incluindo OpenBoard
examples/profile-tools/ Scripts de ações dos perfis
packaging/systemd/      Exemplo de unidade do controlador
docs/                   Documentação por funcionalidade e versões do Studio
tests/                  Testes automatizados
```

## Limitações técnicas e cuidados

- **Linux/`hidraw`:** o suporte atual depende do acesso ao dispositivo `0a00:1000`. A descoberta não depende de um caminho fixo como `/dev/hidraw4`.
- **Permissões:** prefira execução sem `sudo`, configurando o acesso ao dispositivo por permissões adequadas.
- **Confirmação do LCD:** não foi identificado um ACK que confirme a **renderização concluída de cada JPEG**. Uma escrita USB bem-sucedida não prova visualização perfeita; a validação física continua importante.
- **Falhas e reconexão:** há supervisão de hotplug com reinício do processo e espera progressiva. Isso **não** equivale a retransmitir cegamente imagens ou garantir recuperação de qualquer falha.
- **Operação prolongada:** os testes automatizados e as validações do equipamento não representam certificação de estabilidade contínua em todas as máquinas.
- **Dependências externas:** recursos específicos exigem OpenBoard, OBS Studio, autorização Wayland ou outros aplicativos instalados e configurados separadamente.

## Documentação complementar

- [Vision 02 Studio](docs/vision02-studio.md)
- [Editor de propriedades por abas](docs/studio-editor-abas.md)
- [Grade compacta 5 × 3 (v14.1)](docs/studio-deck-compacto-v14-1.md)
- [Galeria ampliada (v14.2)](docs/studio-galeria-vertical-v14-2.md)
- [Menu de Perfis integrado (v15)](docs/studio-menu-perfis-v15.md)
- [Editor interativo de presets (v13)](docs/studio-editor-presets-v13.md)
- [Perfil OpenBoard](docs/perfil-openboard.md)
- [Gerenciamento de perfis](docs/gerenciamento-perfis.md)
- [Recuperação automática USB](docs/hotplug.md)
- [Histórico de alterações](CHANGELOG.md)

---

**Rise Mode Vision 02 Linux** é um projeto independente, desenvolvido por engenharia reversa e testes de integração com hardware real. **Não é um driver ou aplicativo oficial da Rise Mode.**
