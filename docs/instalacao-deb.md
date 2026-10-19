# Instalação do Vision 02 Studio por pacote .deb

O workflow **Build Ubuntu DEB** (`.github/workflows/build-deb.yml`) gera
um `.deb` completo para Ubuntu 24.04 ou posterior. Ele executa primeiro os
testes automatizados e então empacota o código, a interface e exemplos do Studio.

## Baixar pela página Releases (recomendado)

1. Abra **[Releases — versão mais recente](https://github.com/andersonvm/rise-mode-vision02-linux/releases/latest)**.
2. Em **Assets**, baixe `vision02-studio-desktop_15.0.0-1_all.deb` (ou a versão disponível) e `SHA256SUMS`.
3. Abra um terminal na pasta dos downloads e verifique a integridade com `sha256sum -c SHA256SUMS`.
4. Instale o pacote:

```bash
sudo apt install ./vision02-studio-desktop_*_all.deb
```

Isso instala o atalho **Vision 02 Studio** no menu do Ubuntu e o
comando `vision02-studio-control`, que acessa o controlador via IPC:

```bash
vision02-studio-control control status
vision02-studio-control control profiles
```

O pacote **não exige** manter um clone Git ou uma `.venv` pessoal:
os arquivos ficam em `/opt/vision02-studio/` e as dependências
GTK, Pillow, PyYAML e `dbus-next` são obtidas pelo `apt`.

## Releases automáticas

O workflow executa testes de regressão e **instala o pacote num runner Ubuntu 24.04 para validação** antes de publicá-lo.

- Na primeira execução concluída com sucesso na `main`, cria a Release **v15.0.0** e anexa o `.deb` e o `SHA256SUMS`.
- Ao enviar uma **nova** tag `vMAJOR.MINOR.PATCH`, cria uma Release correspondente, sem sobrescrever versões já publicadas.
- Execuções normais na `main` continuam publicando artefatos temporários (30 dias) na [aba Actions](https://github.com/andersonvm/rise-mode-vision02-linux/actions/workflows/build-deb.yml), mas **não substituem o binário da Release v15.0.0**. Para distribuir uma alteração nova, incremente a versão e use uma tag nova.

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

Para publicar uma atualização futura, faça commit de todas as alterações,
crie uma nova tag de versão no commit desejado e envie-a ao GitHub:

```bash
git tag v15.0.1
git push origin v15.0.1
```

**Não reutilize tags de uma Release existente.** Verifique a execução dos testes,
a instalação do pacote e os Assets antes de anunciar a versão.
