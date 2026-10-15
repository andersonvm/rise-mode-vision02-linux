# OBS Studio — cenas por nome e associação em lote

Este módulo corrige a associação por índice (`scene_slot`) e permite associar **até 14 cenas diferentes** às teclas 01–14 da Vision 02. A tecla física 15 continua reservada ao retorno para o perfil Sistema.

## Por que duas teclas apareciam como ATIVA?

O perfil OBS antigo vinculava cenas por posições 1, 2 e 3 na lista devolvida pelo WebSocket. Depois de criar, excluir ou reordenar cenas no OBS, a mesma posição podia representar outra cena. Um perfil misto também podia ter `scene_slot` e `scene_name` apontando para a mesma cena. Além disso, a atualização física não é simultânea: os LCDs recebem quadros sucessivos.

A nova implementação identifica as cenas por **nome exato**, impede novas atribuições duplicadas de nomes, sinaliza vínculos legados duplicados com `DUPLICADA` e atualiza primeiro os indicadores inativos e depois o ativo. Essa priorização reduz estados visualmente contraditórios durante a transição (o polling OBS e a transmissão HID continuam sujeitos a pequenos atrasos).

## Atribuir cinco cenas

1. Crie as cinco cenas **no OBS Studio**. O painel Vision 02 não cria cenas no OBS nem executa comandos de gravação/transmissão para fazer associações.
2. Abra `./scripts/vision02-obs-panel` e clique em **Testar conexão / atualizar cenas**.
3. Clique em **Organizar cenas nas teclas (até 14)…**.
4. Configure **Primeira tecla = 06** e **Quantidade = 5**.
5. Selecione cinco cenas diferentes para as teclas 06, 07, 08, 09 e 10.
6. Confirme a substituição das ações existentes. Esta operação troca as ações antes usadas para avançar/voltar cena nas teclas 09 e 10.
7. Clique em **Aplicar ao dispositivo** para enviar o reload pelo IPC.

As ações permanecem nos perfis pessoais em `~/.config/vision02/profiles/obs-studio.yaml`, sem gravar a senha do OBS no YAML. Imagens e aparência existentes são preservadas. Configurações de aparência personalizada podem sobrepor os indicadores dinâmicos; para exibir os estados ao vivo, mantenha o campo opcional `appearance` ausente nessas teclas.

## Nomes e limite físico

- **OBS Studio**: pode conter quantas cenas o OBS suportar.
- **Vision 02**: tem 15 teclas; o painel permite atribuir cenas por nome às teclas **01–14**, reservando a tecla 15 para voltar.
- Ao salvar, o backend valida unicidade das teclas e cenas; os cinco vínculos são gravados juntos com backup, validação YAML e verificação SHA-256 de concorrência.
- O método legado `scene_slot` continua aceito nos YAML antigos, mas seu significado pode mudar com a ordem devolvida pelo OBS. Prefira `scene_name` para todos os vínculos.

## Testes e ativação

Após atualizar o código, execute `python -m pytest -q` na `.venv` e reinicie `vision02.service` **uma única vez** para carregar o novo renderizador. Mudanças posteriores de vinculação usam apenas **Salvar cenas no YAML** e **Aplicar ao dispositivo**, sem reiniciar o serviço.
