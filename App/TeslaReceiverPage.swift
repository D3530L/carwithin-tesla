import Foundation

/// Head-unit page for browsers without MediaSource or WebCodecs (e.g. the Tesla browser):
/// the picture arrives as an MJPEG stream in an `<img>`, touches go back over the same
/// WebSocket the other pages use. Written in ES5 on purpose: old head-unit engines are common.
enum TeslaReceiverPage {
    static let version = "tesla-1"

    static let html = Data("""
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>CarWithin · 车机模式</title>
<style>
html,body{margin:0;height:100%;background:#000;overflow:hidden;-webkit-user-select:none;user-select:none}
#wrap{position:fixed;top:0;left:0;right:0;bottom:0;display:block}
#v{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain;background:#000}
#msg{position:fixed;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;
color:#ddd;font:16px/1.5 sans-serif;text-align:center;padding:24px;z-index:2}
#ui{position:fixed;left:10px;top:10px;color:#9ab;font:12px/1.5 monospace;z-index:3;opacity:.8;white-space:pre;pointer-events:none}
#bar{position:fixed;right:10px;top:10px;z-index:3}
#bar button{font:13px sans-serif;padding:7px 11px;margin-left:6px;border-radius:7px;border:1px solid #3a3a3a;
background:#1b1b1b;color:#e8e8e8}
#bar button:active{background:#333}
</style></head><body>
<div id="wrap"><img id="v" alt=""></div>
<div id="msg">正在连接 CarWithin…</div>
<div id="ui"></div>
<div id="bar"><button id="fs">全屏</button><button id="st">统计</button></div>
<script>
(function(){
var img=document.getElementById('v'),msg=document.getElementById('msg'),ui=document.getElementById('ui');
var started=false,frames=0,windowFrames=0,windowStart=0,fps=0,showStat=true,ws=null,wsState='未连接';
var vw=0,vh=0;

function setStatus(t){msg.style.display='flex';msg.textContent=t}
function hideStatus(){msg.style.display='none'}

function reload(){
  img.src='/mjpeg?t='+new Date().getTime();
}
img.onload=function(){
  if(!started){started=true;hideStatus()}
  if(img.naturalWidth){vw=img.naturalWidth;vh=img.naturalHeight}
  frames++;windowFrames++;
};
img.onerror=function(){
  if(!started){setStatus('画面还没来，正在重试…（确认 iPhone 上已启动 CarPlay）')}
  setTimeout(reload,1500);
};
reload();

/* ---------- touches ---------- */
var fingers={},nextId=0;
function videoRect(){
  var w=img.clientWidth,h=img.clientHeight,r=img.getBoundingClientRect();
  if(!vw||!vh)return {left:r.left,top:r.top,width:w,height:h};
  var scale=Math.min(w/vw,h/vh),dw=vw*scale,dh=vh*scale;
  return {left:r.left+(w-dw)/2,top:r.top+(h-dh)/2,width:dw,height:dh};
}
function norm(ev){
  var r=videoRect();
  if(r.width<=0||r.height<=0)return null;
  var x=(ev.clientX-r.left)/r.width,y=(ev.clientY-r.top)/r.height;
  if(x<-0.02||x>1.02||y<-0.02||y>1.02)return null;
  return {x:Math.min(1,Math.max(0,x)),y:Math.min(1,Math.max(0,y))};
}
function send(obj){
  if(ws&&ws.readyState===1){try{ws.send(JSON.stringify(obj))}catch(e){}}
}
function publish(){
  var points=[],k;
  for(k in fingers){if(fingers.hasOwnProperty(k)){points.push({id:fingers[k].id,x:fingers[k].x,y:fingers[k].y})}}
  send({type:'touches',points:points});
}
function down(id,ev){
  var p=norm(ev);if(!p)return;
  if(!fingers.hasOwnProperty(id)){fingers[id]={id:nextId,x:p.x,y:p.y};nextId=(nextId+1)%256}
  else{fingers[id].x=p.x;fingers[id].y=p.y}
  publish();
}
function move(id,ev){
  if(!fingers.hasOwnProperty(id))return;
  var p=norm(ev);if(!p)return;
  fingers[id].x=p.x;fingers[id].y=p.y;publish();
}
function up(id){
  if(!fingers.hasOwnProperty(id))return;
  delete fingers[id];publish();
}
var wrap=document.getElementById('wrap');
function evId(e){return (e.pointerId!==undefined)?('p'+e.pointerId):('m0')}
if(window.PointerEvent){
  wrap.addEventListener('pointerdown',function(e){e.preventDefault();down(evId(e),e)});
  wrap.addEventListener('pointermove',function(e){e.preventDefault();move(evId(e),e)});
  wrap.addEventListener('pointerup',function(e){e.preventDefault();up(evId(e))});
  wrap.addEventListener('pointercancel',function(e){up(evId(e))});
  wrap.addEventListener('pointerleave',function(e){up(evId(e))});
}else{
  wrap.addEventListener('mousedown',function(e){e.preventDefault();down('m0',e)});
  wrap.addEventListener('mousemove',function(e){if(fingers['m0'])move('m0',e)});
  window.addEventListener('mouseup',function(e){up('m0')});
  wrap.addEventListener('touchstart',function(e){e.preventDefault();for(var i=0;i<e.changedTouches.length;i++){var t=e.changedTouches[i];down('t'+t.identifier,t)}});
  wrap.addEventListener('touchmove',function(e){e.preventDefault();for(var i=0;i<e.changedTouches.length;i++){var t=e.changedTouches[i];move('t'+t.identifier,t)}});
  wrap.addEventListener('touchend',function(e){e.preventDefault();for(var i=0;i<e.changedTouches.length;i++){up('t'+e.changedTouches[i].identifier)}});
  wrap.addEventListener('touchcancel',function(e){for(var i=0;i<e.changedTouches.length;i++){up('t'+e.changedTouches[i].identifier)}});
}

/* ---------- websocket (touch + keepalive) ---------- */
function connect(){
  if(typeof WebSocket!=='function'){wsState='不支持 WebSocket（只能看，不能点）';return}
  try{
    ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/stream?headunit=1');
    ws.binaryType='arraybuffer';
  }catch(e){wsState='创建失败';return}
  ws.onopen=function(){
    wsState='已连接';
    send({type:'info',text:'车机模式 '+navigator.userAgent.slice(0,120)});
    send({type:'ping',t0:performance.now()});
  };
  ws.onclose=function(){wsState='已断开';fingers={};setTimeout(connect,2000)};
  ws.onerror=function(){wsState='出错'};
  ws.onmessage=function(){};
}
connect();
setInterval(function(){
  send({type:'ping',t0:performance.now()});
  if(!img.complete){reload()}
},10000);

/* ---------- stats ---------- */
document.getElementById('fs').onclick=function(){
  var el=document.documentElement;
  if(document.fullscreenElement){document.exitFullscreen()}
  else if(el.requestFullscreen){el.requestFullscreen()}
  else if(el.webkitRequestFullscreen){el.webkitRequestFullscreen()}
};
document.getElementById('st').onclick=function(){showStat=!showStat;ui.style.display=showStat?'block':'none'};
setInterval(function(){
  var now=new Date().getTime();
  if(!windowStart){windowStart=now;windowFrames=0}
  else if(now-windowStart>=1000){fps=windowFrames*1000/(now-windowStart);windowFrames=0;windowStart=now}
  ui.textContent='MJPEG 车机模式 · 触控 '+wsState+'\n'+
    '画面 '+(vw||'?')+'×'+(vh||'?')+' · '+fps.toFixed(1)+' fps · 累计 '+frames+' 帧';
},1000);
})();
</script>
</body></html>
""".utf8)
}
