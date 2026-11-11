"""Real Chromium QA without any requests to Google or advertiser destinations.

Run with Python + websocket-client and google-chrome-stable in an isolated
container. The tracker is tested against real intersections and image loading.
"""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import websocket


class Browser:
    def __init__(self,url):self.socket=websocket.create_connection(url,timeout=10,suppress_origin=True);self.seq=0
    def call(self,method,params=None):
        self.seq+=1;self.socket.send(json.dumps({'id':self.seq,'method':method,'params':params or {}}))
        while True:
            result=json.loads(self.socket.recv())
            if result.get('id')==self.seq:
                if 'error' in result:raise AssertionError(result['error'])
                return result.get('result',{})
    def js(self,code):
        result=self.call('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in result:raise AssertionError(result['exceptionDetails'])
        return result.get('result',{}).get('value')


def main():
    root=Path(__file__).resolve().parents[1]
    tracker=(root/'app/static/js/ad-analytics.js').read_text()
    with tempfile.TemporaryDirectory() as folder:
        folder=Path(folder)
        raw=base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100"><rect width="300" height="100" fill="red"/></svg>').decode()
        def ad(id,extra=''):
            return f'<a id="{id}" {extra} href="#" data-ad-slide data-ad-promotion-id="trivox-{id}" data-ad-promotion-name="Campanha {id}" data-ad-slot="header_top" data-ad-placement="Topo / Cabecalho"><img src="data:image/svg+xml;base64,{raw}"></a>'
        page=folder/'index.html'
        page.write_text('<style>body{margin:0;min-height:3000px}a{display:block;width:300px;height:100px}a[hidden]{display:none}#below{position:absolute;top:1800px}#tab{position:fixed;top:0}</style>'+
            '<script>window.events=[];window.gtag=(...args)=>events.push(args);</script>'+ad('first')+ad('rotation','hidden')+
            ad('below')+ad('tab','hidden')+ad('broken').replace('id="broken"','id="broken" style="position:absolute;top:110px"').replace('src="data:image/svg+xml;base64,'+raw+'"','src="missing.png"')+
            '<script>'+tracker+'</script>')
        browser=subprocess.Popen(['google-chrome-stable','--headless=new','--no-sandbox','--disable-dev-shm-usage',
            '--disable-background-networking','--no-first-run','--remote-debugging-port=9223',
            '--window-size=1000,700','--user-data-dir='+str(folder/'profile'),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        cdp=None
        try:
            for _ in range(70):
                try:
                    tabs=json.load(urllib.request.urlopen('http://127.0.0.1:9223/json/list',timeout=1))
                    cdp=Browser(next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page'));break
                except Exception:time.sleep(.1)
            assert cdp
            cdp.call('Network.enable');cdp.call('Network.setBlockedURLs',{'urls':['*google-analytics.com*','*googletagmanager.com*','*analytics.google.com*']})
            cdp.call('Page.navigate',{'url':page.as_uri()});time.sleep(.5)
            assert cdp.js('events.length')==0,'No impression before one continuous second'
            time.sleep(.8)
            assert cdp.js("events.map(e=>[e[1],e[2].promotion_id])")==[['view_promotion','trivox-first']]
            cdp.js("first.hidden=true;rotation.hidden=false");time.sleep(1.3)
            assert cdp.js('events.length')==2,'Only the newly visible rotated creative should count'
            cdp.js("rotation.hidden=true;first.hidden=false");time.sleep(1.3)
            assert cdp.js('events.length')==2,'Rotation must not repeat a previously measured creative'
            cdp.js("first.addEventListener('click',e=>e.preventDefault());first.click()")
            assert cdp.js('events.at(-1)[1]')=='select_promotion'
            assert cdp.js('events.at(-1)[2].items[0].promotion_id')=='trivox-first'
            cdp.js('window.scrollTo(0,1700)');time.sleep(.4);cdp.js('window.scrollTo(0,0)');time.sleep(.8)
            assert cdp.js('events.length')==3,'Brief visibility below one second must not count'
            cdp.js('window.scrollTo(0,1860)');time.sleep(1.3)
            assert cdp.js('events.length')==3,'Less than half of a banner must not count'
            cdp.js('window.scrollTo(0,1700)');time.sleep(1.3)
            assert cdp.js('events.at(-1)[2].promotion_id')=='trivox-below'
            cdp.js("Object.defineProperty(document,'hidden',{value:true,configurable:true});document.dispatchEvent(new Event('visibilitychange'));tab.hidden=false")
            time.sleep(1.3);assert cdp.js('events.length')==4,'Background tabs must not generate impressions'
            cdp.js("Object.defineProperty(document,'hidden',{value:false,configurable:true});document.dispatchEvent(new Event('visibilitychange'))")
            time.sleep(1.3);assert cdp.js('events.at(-1)[2].promotion_id')=='trivox-tab'
            assert cdp.js("events.every(e=>e[2].items.length===1&&e[2].items[0].quantity===1)")
            assert cdp.js("!events.some(e=>e[2].promotion_id==='trivox-broken')")
            print(json.dumps({'ok':True,'checks':['one_second','loaded_image','offscreen','half_visible','rotation','deduplication','click','interrupted_visibility','background_tab','ga4_items'],'events':cdp.js('events.map(e=>({event:e[1],id:e[2].promotion_id,slot:e[2].creative_slot}))'),'google_requests_sent':0}))
        finally:
            if cdp:cdp.socket.close()
            browser.terminate();browser.wait(timeout=10)


if __name__=='__main__':main()
