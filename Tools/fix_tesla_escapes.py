import pathlib

p = pathlib.Path('App/TeslaReceiverPage.swift')
s = p.read_text(encoding='utf-8')

# Swift multi-line literals interpret escapes: `\/` is invalid and `\n` becomes a real newline,
# which would break the JS string. Keep backslashes only where JS needs them.
a = r"var base=location.pathname.replace(/[^\/]*$/,'');"
b = r"var base=location.pathname.replace(/[^/]*$/,'');"
assert a in s, 'base anchor missing'
s = s.replace(a, b, 1)

c = r"ui.textContent='MJPEG 车机模式 · 触控 '+wsState+'\n'+"
d = r"ui.textContent='MJPEG 车机模式 · 触控 '+wsState+'\\n'+"
assert c in s, 'textContent anchor missing'
s = s.replace(c, d, 1)
p.write_text(s, encoding='utf-8')
print('escapes fixed')
