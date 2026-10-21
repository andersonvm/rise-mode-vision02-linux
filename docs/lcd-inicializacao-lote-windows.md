# Inicialização dos 15 LCDs sem bordas brancas

## Evidência física

No Vision02 USB HID `0a00:1000` (revisão USB `0300`), o aplicativo oficial Windows transmitiu `CLE FF`, 15 imagens JPEG 100×100 e um único `STP`. Um teste reproduzindo essa sequência uma vez no Ubuntu eliminou as bordas brancas. Após restaurar `vision02.service`, os ícones continuaram corretos. O comportamento após inicialização a frio com o patch integrado ainda precisa ser validado.

## Implementação

- `Vision02.set_images_batch()`: requer os 15 displays, codifica JPEGs antecipadamente, envia `CLE FF`, 15 `BAT` e um `STP` sob bloqueio de transmissão. Atualiza cache só após sucesso; erros invalidam a sessão.
- `cli._run_profile()`: usa o lote **somente ao carregar o perfil inicial**.
- `MirroredDevice.set_images_batch()`: publica as prévias após conclusão do lote.
- `set_image()`, métricas dinâmicas, troca e recarga de perfis permanecem individuais.

## Validação antes do merge

1. `PYTHONPATH=src .venv/bin/python -m pytest -q`
2. Reiniciar o serviço e verificar 15 ícones, métricas, prévias e menu de perfis.
3. Fazer um desligamento completo e uma inicialização a frio **sem executar a VM Windows**.
4. Confirmar ausência de bordas brancas.
5. Se houver regressão, voltar à versão anterior sem modificar YAMLs pessoais.

**Não há atualização de firmware nem gravação persistente nesta alteração.** O comportamento é validado apenas na revisão de hardware indicada.
