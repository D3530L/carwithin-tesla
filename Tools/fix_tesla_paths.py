import pathlib

p = pathlib.Path('App/TeslaReceiverPage.swift')
s = p.read_text(encoding='utf-8')
a = "img.src='/mjpeg?t='+new Date().getTime();"
b = "img.src=base+'mjpeg?t='+new Date().getTime();"
assert a in s, 'img.src anchor missing'
s = s.replace(a, b, 1)

c = "ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/stream?headunit=1');"
d = "ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+base+'stream?headunit=1');"
assert c in s, 'websocket anchor missing'
s = s.replace(c, d, 1)
p.write_text(s, encoding='utf-8')
print('TeslaReceiverPage patched to relative paths')
