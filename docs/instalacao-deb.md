# Instalação do Vision 02 Studio por pacote .deb

O workflow **Build Ubuntu DEB** (`.github/workflows/build-deb.yml`) gera
um `.deb` completo para Ubuntu 24.04 ou posterior. Ele executa primeiro os
testes automatizados e então empacota o código, a interface e exemplos do Studio.

## Baixar pelo GitHub Actions

1. Abra [Actions → Build Ubuntu DEB](https://github.com/andersonvm/rise-mode-vision02-linux/actions/workflows/build-deb.yml).
2. Clique em **Run workflow**, selecione `main` e execute; ou use o artefato
   de uma execução bem-sucedida na branch `main`.
3. Baixe o artefato `vision02-studio-deb-*` e extraia o ZIP baixado pelo GitHub.
4. Instale o `.deb` com duplo clique ou no terminal:

```bash
sudo apt install ./vision02-studio-desktop_*.deb
```

O pacote instala o atalho **Vision 02 Studio** no menu do Ubuntu e o
comando `vision02-studio-control` para conversar com o controlador via IPC:

```bash
vision02-studio-control control status
vision02-studio-control control profiles
```

O pacote **não exige** manter um clone Git ou uma `.venv` pessoal:
os arquivos são instalados sob `/opt/vision02-studio/` e as dependências
GTK, Pillow, PyYAML e `dbus-next` são obtidas pelo `apt`.

## Serviço HID e atualizações

- Este instalador **não instala ou ativa automaticamente** o serviço de
  controlador HID: isso poderia disputar o USB com uma instalação existente.
- A GUI funciona desconectada, mas os comandos que alteram os LCDs precisam
  de um controlador em execução com IPC. Consulte [hotplug](hotplug.md) e
  [gerenciamento de perfis](gerenciamento-perfis.md) para configurá-lo.
- Atualizações futuras dessa instalação são feitas instalando novos arquivos
  `.deb`. **Não aplique os ZIPs do antigo gerenciador de código-fonte**
  sobre `/opt/vision02-studio`.
- O nome do pacote é `vision02-studio-desktop`, o mesmo usado anteriormente
  para instalar apenas atalhos e o gerenciador de atualização. A nova versão
  substitui esse pacote pelo Studio completo. O antigo gerenciador ZIP
  **não faz parte deste .deb**.
- Perfis em `~/.config/vision02/`, backups, credenciais OBS e serviços
  systemd já existentes não são modificados na instalação.

## Gerar localmente

```bash
python3 packaging/debian/build_deb.py --version 15.0.0 --output dist
dpkg-deb --info dist/*.deb
```

O construtor utiliza a biblioteca padrão do Python e `dpkg-deb`.
Os testes automatizados devem ser executados antes da distribuição.

## Publicação via tag

Uma tag `v15.0.0` também aciona o workflow. Após os testes, o `.deb`
e `SHA256SUMS` são anexados à **Release** daquela tag.
Execuções manuais e pushes na `main` publicam somente um artefato
temporário do GitHub Actions (retenção de 30 dias).
