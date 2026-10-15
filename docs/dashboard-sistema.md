# Vision 02 · dashboard do perfil Sistema

O dashboard é um componente **opcional e automático** do processo `vision02 profile run --catalog`.

## Comportamento

Somente ao ativar o perfil pessoal denominado **`Sistema`**, as teclas físicas
com os rótulos abaixo passam a apresentar dados reais (sem modificar o YAML):

| Tecla física | Rótulo YAML | Informação no LCD | Ação ao pressionar |
|---|---|---|---|
| 01 | `CPU` | Uso de CPU e temperatura (se detectada) | Inalterada |
| 02 | `RAM` | Uso percentual e memória utilizada em GiB | Inalterada |
| 03 | `GPU` | Ocupação da GPU ou `N/D` | Inalterada |
| 04 | `DISCO` | Espaço utilizado na partição `/` | Inalterada |
| 05 | `REDE` | Tráfego recebido/enviado, bytes por segundo | Inalterada |

Para mostrar **temperatura em destaque**, altere apenas o rótulo físico 04 de
`DISCO` para `TEMP` ou `TEMPERATURA` no editor. A ação da tecla permanece
inalterada; ajuste-a separadamente se desejar. A CPU continua mostrando a
temperatura na parte inferior do ícone.

O dashboard **não substitui** imagens de teclas com aparência avançada
explicitamente configurada, nem teclas cujos rótulos não correspondem aos
valores esperados. Isso protege personalizações visuais do usuário.

Os displays são atualizados somente no perfil `Sistema`. Ao sair do perfil, o
renderizador original assume; ao retornar, os valores são novamente desenhados.
O perfil pessoal e a biblioteca de ícones **não são modificados**.

## Fontes e limitações

- CPU: diferenças entre amostras de `/proc/stat` (a primeira pode indicar `N/D`).
- RAM: `MemAvailable` em `/proc/meminfo`.
- GPU: `gpu_busy_percent` em `/sys/class/drm` ou `nvidia-smi`, quando disponível.
- Temperatura: sensores de CPU em `/sys/class/hwmon` ou `/sys/class/thermal`.
- Disco: uso do filesystem que contém `/` (não mede I/O).
- Rede: diferenças dos contadores de interfaces físicas em `/proc/net/dev`,
  sem incluir interfaces virtuais comuns. RX/TX são taxas aproximadas.

Sensores indisponíveis são mostrados como **N/D**. A coleta ocorre numa
thread separada a cada **8 segundos**. Somente o loop proprietário do USB/HID
envia imagens, até **uma tecla por passagem**, com um intervalo mínimo de
200 ms e cache de conteúdo no driver. As outras dez teclas não são atualizadas.

**Não se trata de uma série histórica ou de uma ferramenta de medição de
precisão.** Os valores arredondados servem para acompanhamento rápido.

## Ativação

Instale o módulo pelo instalador de atualização e reinicie o serviço apenas
**uma vez** para carregar o Python atualizado:

```bash
systemctl --user restart vision02.service
.venv/bin/vision02 control switch Sistema
.venv/bin/vision02 control status
```

As teclas 1–5 passarão a mostrar os dados após as primeiras coletas. Troque
para `Observabilidade` e retorne a `Sistema` para validar o isolamento visual.
A alternância, IPC e o hotplug permanecem disponíveis.

## Desativação

A maneira mais simples de não transmitir dados dinâmicos é selecionar qualquer
outro perfil. Para desinstalar o módulo, restaure os arquivos de backup do
instalador (leia a saída de `--apply`) com o serviço parado e reinicie o serviço.
Não é necessário editar ou apagar os YAML pessoais.

## Problemas comuns

- `GPU: N/D`: driver não disponibiliza uso por sysfs nem por `nvidia-smi`.
- `TEMP N/D`: não há sensor de temperatura legível para o usuário.
- LCDs estáticos: confira `vision02 control status`; perfil precisa se chamar
  `Sistema`, rótulos precisam corresponder e a aparência avançada deve estar
  desabilitada nas teclas monitoradas.
- Monitoramento não deve causar consumo HID em outros perfis. Erros de escrita
  USB provocam encerramento do processo controlador, permitindo recuperação
  pelo supervisor já existente.
