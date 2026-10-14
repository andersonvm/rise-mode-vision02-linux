# Interface gráfica da Vision 02

Interface inicial GTK 4/libadwaita para GNOME Wayland. **Não acessa o USB/HID**; o controlador continua sendo o processo filho gerenciado pelo supervisor `vision02.service`.

## Inicialização

```bash
cd ~/projetos/rise-mode-vision02/rise-mode-vision02-linux
./scripts/vision02-gui
```

A janela utiliza `/usr/bin/python3`, porque `gi` foi instalado via `apt` no Python do sistema. As miniaturas são geradas uma única vez por `.venv/bin/python` através de `apps/vision02_gui_data.py`, reutilizando o renderizador do projeto. Não instale `gi` na `.venv` para esta etapa.

## Funcionalidades

- Indica se o controlador IPC está disponível e consulta seu estado a cada 3 segundos, sem bloquear a janela.
- Exibe as 15 teclas na disposição física 5×3, com prévias iguais às renderizadas para os displays.
- Selecionar uma tecla mostra seu rótulo, tipo de ação e número LCD BAT; **não executa a ação**.
- Seletor de perfil envia `switch` ao controlador via socket IPC e atualiza as prévias.
- O controle HID é exclusivo do serviço. Se o periférico desconectar, o painel indica indisponibilidade e se recupera após o socket reaparecer.

Os arquivos dos perfis visualizados são `examples/profiles/desenvolvimento-switch.yaml` e `examples/profiles/observabilidade.yaml`. O controlador decide quais perfis estão disponíveis; a interface **não adiciona perfis por conta própria**. As imagens ficam em `~/.cache/vision02/gui`.

## Limites desta versão

A interface ainda não edita YAML, não executa ações e não controla o `systemd`. A visualização corresponde à versão em disco dos arquivos YAML quando a janela foi aberta; se forem alterados, feche e abra a janela para atualizar. A seleção de perfis depende do serviço já executando o IPC (`vision02 control status`).
