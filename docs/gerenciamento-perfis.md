# Gerenciamento de perfis da Vision 02

Os arquivos pessoais vivem em `$XDG_CONFIG_HOME/vision02/profiles/`
(`~/.config/vision02/profiles/` por padrão). O gerenciador GTK é iniciado por:

```bash
./scripts/vision02-profiles
```

O painel principal e o editor de teclas também oferecem **Gerenciar perfis**.
O editor possui botão para atualizar a lista quando novos perfis são criados.

## Operações

- **Criar:** cria um YAML vazio, válido, com o nome indicado.
- **Duplicar:** cria uma cópia do perfil, com novo nome. Imagens e scripts são
  compartilhados; não são duplicados no disco.
- **Renomear:** atualiza o nome dentro do YAML e os destinos das ações
  `type: profile` nos demais YAML. Para manter recursos relativos funcionando,
  o nome físico do arquivo `.yaml` é preservado.
- **Excluir:** só permite apagar um perfil que não esteja ativo e não seja
  referenciado por outros. Não permite excluir o último perfil.
- **Definir como inicial:** atualiza `~/.config/vision02/settings.json`. A opção
  **Restaurar último perfil ativo** tem precedência sobre o perfil inicial,
  quando o último perfil ainda existir.
- **Aplicar ao dispositivo:** usa `vision02 control reload`, sem abrir outra
  conexão USB/HID e sem reiniciar o `systemd`. O perfil ativo é preservado.

O controle IPC rejeita `reload` se o perfil ativo desapareceu dos YAML.
O gerenciador impede excluir ou renomear esse perfil quando o serviço está
conectado. Para alterar o perfil em uso, selecione outro no painel antes.

## Persistência

O último perfil é salvo em `$XDG_STATE_HOME/vision02/last-profile.json`
(`~/.local/state/vision02/last-profile.json` por padrão) **depois de cada
transição bem-sucedida** via tecla física ou comando IPC.
O processo iniciado com `vision02 profile run --catalog --ipc` escolhe o último
perfil válido, quando habilitado, ou o perfil inicial configurado.

O supervisor usa `python -m vision02.hotplug --catalog` para descobrir todos
os YAML na inicialização e reconexão. O `control reload` relê a lista dinâmica.
Perfis explícitos via `vision02 profile run arquivo.yaml --with outro.yaml`
continuam funcionando como antes.

## Integridade e recuperação

As operações no catálogo usam lock local, versão SHA-256, validação do conjunto,
backup em `~/.local/state/vision02/profile-backups/`, arquivos temporários
com permissões restritas e substituição atômica por arquivo. Uma gravação que
falhe tenta restaurar os arquivos anteriores. **Uma transação que envolva vários
YAML não é atomicamente recuperável após uma queda abrupta do sistema:** os
backups permitem recuperação manual.

O editor de teclas salva apenas um YAML, com sua própria checagem de versão.
Se usar editor e gerenciador simultaneamente, evite salvar o mesmo perfil nos
dois até concluir uma operação e recarregar a outra janela.

## Ativação do serviço

A nova descoberta dinâmica exige **uma única reinicialização** do serviço após
instalar o código e ativar o drop-in `zz-vision02-catalog.conf`. A unidade
anterior e o drop-in `profiles.conf` são preservados.

```bash
systemctl --user is-active vision02.service
.venv/bin/vision02 control status
./scripts/vision02-profiles
```

Na primeira inicialização do novo serviço, os perfis ainda não são modificados;
a descoberta considera todos os arquivos `*.yaml` do diretório pessoal.
