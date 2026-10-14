# Perfis pessoais da Vision 02

O editor e o painel consultam os dois perfis localizados em
`$XDG_CONFIG_HOME/vision02/profiles/` (por padrão `~/.config/vision02/profiles/`).
O serviço `vision02.service` carrega os mesmos arquivos, por meio de um
override `~/.config/systemd/user/vision02.service.d/profiles.conf`.

- `desenvolvimento.yaml`: inclui personalizações atuais, inclusive a tecla 05.
- `observabilidade.yaml`: perfil complementar.
- Imagens e scripts referenciados são copiados para `$XDG_DATA_HOME/vision02/assets/`
  caso sejam caminhos relativos ao YAML original; os caminhos novos tornam-se absolutos.
- Os exemplos versionados em `examples/profiles/` permanecem intocados.
- `--apply` NÃO reinicia o controlador.
- `--activate` altera apenas o drop-in do systemd e reinicia o serviço.

Após ativar, feche e reabra o painel e o editor, confirme `vision02 control status`
e teste a tecla 15. Os YAML pessoais não devem ser adicionados ao Git.

Para voltar ao serviço anterior, remova **apenas** o drop-in `profiles.conf`
(criado nesta migração), recarregue e reinicie: `systemctl --user daemon-reload`
e `systemctl --user restart vision02.service`. As cópias dos YAML são preservadas.
