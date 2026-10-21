# Rise Mode Vision 02 Linux

**Vision02 Studio v1.0.0 — primeira versão estável.** Aplicativo independente para Linux que controla as **15 teclas físicas com LCDs individuais (100 × 100 px)** do Rise Mode Vision 02. Inclui interface gráfica GTK4/libadwaita, perfis configuráveis, integração OBS Studio e controlador USB/HID supervisionado.

[**Baixar v1.0.0 (.deb)**](https://github.com/andersonvm/rise-mode-vision02-linux/releases/tag/v1.0.0) · [Última release](https://github.com/andersonvm/rise-mode-vision02-linux/releases/latest) · [Instalação detalhada](docs/instalacao-deb.md) · [Documentação do Studio](docs/vision02-studio.md)

> Projeto comunitário de engenharia reversa, **não oficial e não afiliado à Rise Mode**. Validado em hardware real no Ubuntu. A numeração pública recomeçou em v1.0.0; a antiga [v15.0.0](https://github.com/andersonvm/rise-mode-vision02-linux/releases/tag/v15.0.0) foi preservada apenas como histórico.

## Instalação rápida — Ubuntu 24.04+

Baixe os dois arquivos nos *Assets* da [release v1.0.0](https://github.com/andersonvm/rise-mode-vision02-linux/releases/tag/v1.0.0):

- `vision02-studio-desktop_1.0.0-1_all.deb`
- `SHA256SUMS`

Na pasta onde foram baixados:

```bash
sha256sum -c SHA256SUMS
sudo apt install ./vision02-studio-desktop_1.0.0-1_all.deb
```

O pacote instala a GUI e seus componentes em `/opt/vision02-studio/`, além do atalho **Vision 02 Studio** e dos comandos `vision02-studio-launch` e `vision02-studio-control`. Para iniciar:

```bash
vision02-studio-launch
```

**Importante:** o `.deb` **não instala nem ativa automaticamente o serviço HID**. Um controlador já ativo, com IPC habilitado, é necessário para modificar as teclas. A GUI pode abrir sem o equipamento conectado, mas não conseguirá aplicar comandos ao hardware. Veja [serviço e hotplug](docs/hotplug.md), [IPC](docs/ipc.md) e [instalação Debian](docs/instalacao-deb.md). O instalador preserva perfis pessoais e configurações OBS.

Se você usou um pacote experimental `16.0.0~rc1-1`, o APT considerará `1.0.0-1` um **downgrade numérico**. A v1.0.0 é a nova linha estável; revise essa operação antes de confirmá-la.

## Funcionalidades

| Área | Recursos disponíveis |
| --- | --- |
| **Hardware** | Descoberta USB/HID por VID:PID `0a00:1000`, 15 teclas físicas e 15 LCDs 100 × 100, imagens JPEG e cache seletivo |
| **Inicialização dos LCDs** | Sequência em lote `CLE FF` → 15 JPEGs → `STP` único, validada sem bordas brancas após inicialização a frio |
| **Brilho** | Controle **global** de 0 a 100% dos 15 LCDs pelo Studio e CLI, com preferência persistente e restauração ao reconectar |
| **Vision02 Studio** | Painel GTK4/libadwaita, grade física 5 × 3, propriedades por tecla, abas Ação / Imagem / Texto / Composição |
| **Edição visual** | Preview dos LCDs, composição de imagens e texto, galeria de ícones, presets e aplicação via IPC |
| **Perfis** | Catálogo pessoal YAML, criação, duplicação, renomeação, seleção e troca de perfis com persistência do último perfil |
| **Menu de Perfis** | Navegação pelos perfis nos LCDs; tecla 15 como acesso/retorno ao menu, com paginação |
| **Ações e integrações** | Comandos, URLs, scripts, atalhos, troca de perfil, OBS WebSocket 5.x e indicadores do sistema |
| **Confiabilidade** | Sessão HID persistente, serialização de operações, supervisor de conexão USB, recuperação após reconexão e IPC Unix local |

### Ajustar o brilho

No **Studio → Configurações → Brilho das teclas LCD (global)**, selecione um percentual e clique em **Aplicar brilho**.

Com o serviço em execução, também é possível usar o terminal:

```bash
vision02-studio-control control brightness       # Consultar
vision02-studio-control control brightness 60    # Aplicar 60%
vision02-studio-control control brightness 100   # Aplicar 100%
```

O brilho é aplicado **aos 15 LCDs simultaneamente**, não individualmente. A preferência fica em `~/.config/vision02/brightness.json` (ou `XDG_CONFIG_HOME`). Se os LCDs forem apagados com 0%, recupere pelo comando `control brightness 25`. [Protocolo e detalhes](docs/brilho-lcd.md).

### Perfis e Menu de Perfis

Os perfis pessoais são armazenados em `~/.config/vision02/profiles/`. No Studio, acesse **Menu de Perfis**, inspecione o catálogo e revise a configuração da **tecla 15** antes de sincronizar: a sincronização substitui sua ação anterior nos perfis incluídos, com backup para restauração. Depois utilize **Recarregar catálogo (IPC)** e **Abrir menu nos LCDs (IPC)**.

Há um [perfil de exemplo para OpenBoard](docs/perfil-openboard.md), incluindo ícones e atalhos. Aplicativos como OpenBoard e OBS devem estar instalados/configurados separadamente.

## Arquitetura

```text
Vision02 Studio (GTK4/libadwaita)
   │
   ├── Editor, perfis, imagens, OBS e brilho
   │
   ▼
Backend do Studio → socket IPC Unix
   │
   ▼
Controlador Vision02 (único proprietário do HID)
   │
   ▼
Supervisor hotplug / serviço systemd --user
   │
   ▼
Linux hidraw → Rise Mode Vision 02 (15 teclas / 15 LCDs)
```

**Não execute uma segunda instância que abra `/dev/hidraw*` enquanto o serviço controla o dispositivo.** A GUI e os comandos `control` comunicam-se com o processo existente via IPC; a VM Windows/VirtualBox também não pode possuir o dispositivo ao mesmo tempo.

Verificações úteis com o serviço já configurado:

```bash
systemctl --user is-active vision02.service
journalctl --user -u vision02.service -n 40 --no-pager
vision02-studio-control control status
vision02-studio-control control profiles
vision02-studio-control control reload
```

O `reload` relê os perfis sem abrir outra sessão HID. Para criar e configurar o serviço pela primeira vez, consulte a [documentação de hotplug](docs/hotplug.md) e o [exemplo de unidade](packaging/systemd/vision02.service): os caminhos precisam ser adaptados à instalação. **Não copie o exemplo sem conferir `WorkingDirectory` e `ExecStart`.**

## Desenvolvimento a partir do código-fonte

Requer Python 3.10+, Pillow, PyYAML, GTK4, libadwaita, PyGObject e acesso ao dispositivo `hidraw`. No Ubuntu, instale as dependências de sistema e crie um ambiente virtual:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip \
  python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

git clone https://github.com/andersonvm/rise-mode-vision02-linux.git
cd rise-mode-vision02-linux
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e '.[dev,wayland]'
./scripts/vision02-studio
```

O launcher local do Studio utiliza o Python do sistema para GTK4; o backend utiliza a instalação Python correspondente. O funcionamento de funcionalidades específicas exige as dependências externas aplicáveis (OBS, OpenBoard, autorização do portal Wayland ou `xdotool` no X11).

### Testes e build Debian

```bash
.venv/bin/python -m pytest -q
python3 packaging/debian/build_deb.py --version 1.0.0 --output dist
```

Na consolidação da v1.0.0, **1.602 testes passaram** na árvore integrada e novamente em uma cópia Git limpa. O [GitHub Actions da v1.0.0](https://github.com/andersonvm/rise-mode-vision02-linux/actions) validou testes, conteúdo e instalação do pacote no Ubuntu 24.04. Os testes automatizados não substituem a verificação física: a ausência de bordas brancas após desligamento completo e o controle/persistência de brilho foram confirmados no equipamento.

A distribuição pública é gerada **a partir de commits versionados**, sem incorporar YAMLs pessoais, credenciais OBS nem scripts locais de diagnóstico. Releases estáveis são publicadas por tags `vMAJOR.MINOR.PATCH`; a [v1.0.0](https://github.com/andersonvm/rise-mode-vision02-linux/releases/tag/v1.0.0) é a primeira da nova numeração.

## Estrutura e documentação

```text
apps/                   Studio GTK4 e backends
src/vision02/           Protocolo, HID, brilho, IPC, perfis e OBS
scripts/                Inicializadores e ferramentas gráficas
examples/               Perfis, ícones e scripts de exemplo
packaging/              Pacote Debian e exemplo de serviço
docs/                   Manuais e protocolos
tests/                  Testes automatizados
```

Consulte a documentação por área: [Studio](docs/vision02-studio.md) · [Brilho dos LCDs](docs/brilho-lcd.md) · [Inicialização sem bordas](docs/lcd-inicializacao-lote-windows.md) · [Perfis](docs/gerenciamento-perfis.md) · [Menu de Perfis](docs/studio-menu-perfis-v15.md) · [OBS WebSocket](docs/integracao-obs-websocket.md) · [Ações e atalhos](docs/acoes.md) · [Notas da v1.0.0](docs/release-v1.0.0.md) · [Histórico](CHANGELOG.md).

## Limitações e segurança

O projeto depende de Linux/`hidraw` e de permissões adequadas para o USB; prefira execução como usuário normal. O firmware não oferece um ACK individual comprovando que cada JPEG já foi exibido, portanto falhas de renderização exigem validação visual. A recuperação de hotplug não equivale a garantir disponibilidade em qualquer ambiente, e o funcionamento prolongado depende de condições de hardware e sistema. **Nunca publique** `~/.config/vision02/obs.json`, dados pessoais de perfis ou capturas USB que contenham informações sensíveis.

---

**Rise Mode Vision 02 Linux** — controlador e Studio comunitários, não oficiais.
