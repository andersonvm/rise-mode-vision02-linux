# Painel OBS Studio — Vision 02

Painel GTK4/libadwaita para associar comandos OBS WebSocket 5.x às teclas do perfil pessoal **OBS Studio**, sem editar YAML manualmente.

## Abrir

```bash
./scripts/vision02-obs-panel
```

Também disponível pelos botões **Configurar OBS** da janela principal e do editor de teclas.

## Como usar

1. Inicie o OBS Studio e habilite seu servidor WebSocket 5.x com autenticação; mantenha `~/.config/vision02/obs.json` configurado com permissões `0600`.
2. Clique em **Testar conexão / atualizar cenas**. A janela mostra versão, cenas, entradas e os estados de gravação, transmissão e câmera virtual. Essa ação envia apenas consultas (`Get*`).
3. Escolha uma tecla física de **01 a 14**; a 15 permanece reservada para voltar ao perfil Sistema.
4. Selecione o comando. A opção **Selecionar cena por nome** usa a lista real do OBS, evitando a fragilidade dos slots por posição (`scene_slot`). Para o microfone/áudio, selecione uma entrada real ou deixe em **Automática**.
5. Clique **Salvar associação no YAML**. A gravação cria backup e respeita o hash SHA-256 original, rejeitando modificações concorrentes. Ícones e aparência avançada são preservados.
6. Clique em **Aplicar ao dispositivo** para acionar o IPC `reload` sem reiniciar `vision02.service`.

O painel **não executa operações de gravação ou transmissão**: elas só acontecem ao pressionar uma tecla física configurada. A operação `toggle_stream` pede confirmação antes de ser associada, pois pressioná-la poderá iniciar uma live real.

## Arquitetura

- `apps/vision02_obs_panel.py`: GTK com consultas assíncronas; usa `/usr/bin/python3` para PyGObject.
- `apps/vision02_obs_panel_backend.py`: backend na `.venv` com acesso ao OBS local e ao editor YAML. **Nunca devolve a senha** para a interface.
- `src/vision02/obs_control.py`: executa `scene_name` via `SetCurrentProgramScene` com o nome exato; mantém `scene_slot` para perfis antigos.
- `src/vision02/profiles/loader.py`: valida `action: {type: obs, operation: scene_name, scene: 'Nome exato'}`.
- `vision02.control_ipc`: aplica as alterações na thread HID. A interface não abre o dispositivo.

O painel não altera `obs.json` nem grava credenciais no YAML. Se uma cena tiver sido removida do OBS, a tecla retorna um erro controlado em vez de tentar uma cena diferente.

Exemplo de configuração de tecla:

```yaml
6:
  label: Câmera
  action:
    type: obs
    operation: scene_name
    scene: 'Câmera USB'
```

## Diagnóstico

```bash
./scripts/vision02-obs-test
.venv/bin/python -m pytest -q
.venv/bin/vision02 control status
journalctl --user -u vision02.service -n 80 --no-pager
```

Para a primeira ativação deste código, reinicie uma vez `systemctl --user restart vision02.service`; alterações posteriores nas teclas usam **Aplicar ao dispositivo**.

A funcionalidade GTK precisa ser validada visualmente no Ubuntu GNOME: o ambiente de testes offline não possui PyGObject.
