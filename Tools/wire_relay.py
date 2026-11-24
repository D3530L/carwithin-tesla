import pathlib

srv = pathlib.Path('App/VideoOutputServer.swift')
s = srv.read_text(encoding='utf-8')

old = """        clients.removeAll()
        primaryBrowser = nil; returningViewer = nil; nextBrowserOrder = 0"""
new = """        clients.removeAll()
        relay?.stop(); relay = nil
        primaryBrowser = nil; returningViewer = nil; nextBrowserOrder = 0"""
assert old in s, 'stopOnQueue anchor missing'
s = s.replace(old, new, 1)

old2 = """        stopOnQueue()
        self.browserAudio = browserAudio"""
new2 = """        stopOnQueue()
        startRelayIfConfigured()
        self.browserAudio = browserAudio"""
assert old2 in s, 'startOnQueue anchor missing'
s = s.replace(old2, new2, 1)
srv.write_text(s, encoding='utf-8')
print('VideoOutputServer patched')

plist = pathlib.Path('App/Info.plist')
t = plist.read_text(encoding='utf-8')
if 'CarWithinRelayHost' not in t:
    t = t.replace('</dict>\n</plist>',
                  '\t<key>CarWithinRelayHost</key>\n'
                  '\t<string>carwithin-relay.poki-yg.workers.dev</string>\n'
                  '</dict>\n</plist>')
    plist.write_text(t, encoding='utf-8')
    print('Info.plist patched')
else:
    print('Info.plist already has the key')
