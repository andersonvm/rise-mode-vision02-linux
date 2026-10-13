"""Exemplo sem executar comandos do sistema."""
from vision02 import Vision02

with Vision02() as device:
    device.on_press(1, lambda key: print(f"Pressionou: {key}"))
    device.on_release(1, lambda key: print(f"Soltou: {key}"))
    device.run()
