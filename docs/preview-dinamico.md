# Prévia dinâmica dos 15 displays — Vision 02 Studio

## Funcionamento

O serviço `vision02 profile run --catalog --ipc`, único proprietário do HID,
cria um espelho da **última imagem enviada com sucesso** a cada um dos 15 LCDs.
O espelho é produzido pela classe `MirroredDevice`, que delega ao dispositivo
real e só publica a imagem **depois** do retorno de `set_image()` sem exceção.
Não abre outro dispositivo, não transmite relatórios HID adicionais, não muda
as ações das teclas e não reconstrói a imagem a partir dos YAML.

O protocolo envia JPEG com rotação de 180°. O espelho decodifica esse mesmo
JPEG e inverte a rotação para apresentar a imagem na orientação vista pelo
usuário. Há diferenças inevitáveis entre o preview digital e o LCD físico
(brilho/cores/óptica), mas o conteúdo vem do JPEG codificado para o display.

O socket privado `control.sock` aceita `display_preview` sem argumentos.
Retorna `active`, `available`, `revision` e 15 caminhos de PNG por **número de
tecla física** (01–15). Não envia bytes grandes pelo socket e não expõe a
senha do OBS, perfil YAML ou diretórios arbitrários.

Os arquivos ficam em `$XDG_RUNTIME_DIR/vision02/display-preview/`, com
permissões 0700 na pasta e 0600 por PNG, usando substituição atômica. Arquivos
sobrantes de uma sessão anterior são descartados no início da nova sessão.
A revisão aumenta apenas quando os pixels publicados mudam; uma transmissão
HID incompleta não atualiza o espelho. Se ocorrer uma falha de geração/gravação
da prévia, ela fica indisponível, **sem interromper o controlador USB**.

## Uso

Após instalar a atualização e reiniciar `vision02.service` uma vez:

```bash
.venv/bin/vision02 control display_preview
./scripts/vision02-studio
```

Na seção **Teclas**, as imagens são atualizadas a cada dois segundos enquanto
a página estiver visível. O Studio carrega os PNG pela saída do IPC, sem
abrir uma conexão HID ou iniciar processos OBS. Se o serviço não disponibilizar
a prévia, a interface mantém a renderização estática do perfil YAML e informa
que se trata de uma prévia, não de uma captura ao vivo.

Mudar o perfil por IPC, tecla física ou editor atualiza os quadros automaticamente.
Atualizações de CPU, RAM, GPU, rede e indicadores OBS também aparecem na grade
conforme o controlador efetivamente transmite os LCDs.

## Limites

- O espelho registra o resultado de `set_image()` (transmissão de bytes
  concluída), **não é leitura óptica** nem confirmação de firmware.
- Os PNG só estão disponíveis na **sessão com IPC habilitado**.
- O comando `display_preview` é somente-leitura e possui a mesma autenticação
  por usuário local dos outros comandos IPC.
- O Studio não mostra valores futuros na fila de atualização do dashboard;
  somente as imagens que já passaram por `set_image()`.
- O Studio não gera tráfego USB adicional.
