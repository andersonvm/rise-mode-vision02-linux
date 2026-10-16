# Vision 02 Studio — interface central GTK4/libadwaita

Execute `./scripts/vision02-studio` em sua sessão gráfica Wayland.

## Organização

- **Dashboard:** estado da Vision 02, perfil ativo e atalhos.
- **Teclas:** prévia das 15 teclas em matriz 5 × 3; clique apenas inspeciona.
- **Perfis:** lista e alternância de perfis via socket IPC privado; recarregar catálogo.
- **Ícones:** pesquisa e importação de imagens na biblioteca pessoal.
- **Sistema:** consulta somente leitura de CPU, RAM, GPU, disco, temperatura e rede.
- **OBS Studio:** consulta somente leitura da conexão WebSocket local e dos estados de gravação, transmissão e câmera virtual.
- **Configurações:** caminhos dos diretórios pessoais e acesso a ferramentas legadas.

O Studio integra as tarefas de consulta e navegação numa só janela. Operações
avançadas, como editar YAML, organizar cenas e ajustar o mixer, **abrem
intencionalmente os editores GTK já existentes**. Isso evita duplicar a lógica
transacional, as confirmações de operações OBS e o gerenciamento do USB/HID.

Arquitetura: `/usr/bin/python3` (GTK via gi) → `apps/vision02_studio_backend.py`
na `.venv` (Pillow, YAML e rede), em comandos JSON por subprocesso; operações
custosas são executadas fora da thread GTK. O Studio nunca abre hidraw nem
requer sudo. Os comandos `status`, `switch` e `reload` usam exclusivamente o IPC.

No momento, as prévias de tecla não são reconstruídas a cada alteração visual:
use **Atualizar prévias** ou alterne o perfil para carregar novas imagens.

## Instalação

Instale via instalador de versão, sem reiniciar o serviço. O aplicativo não
altera automaticamente inicialização do Ubuntu nem substitui a GUI anterior.

`./scripts/vision02-studio`

Para validação:

`.venv/bin/python -m pytest -q`

Os perfis pessoais, as credenciais `obs.json`, os ícones e o serviço systemd
não são modificados pela instalação.
