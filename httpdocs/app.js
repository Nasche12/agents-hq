'use strict';
/* ================================================================
   AGENT HQ – Command Center
   Neues Shell/Design (Vorlage) + unsere echte Orbital-Karte (Canvas)
   + echte Datenanbindung: status.json, uptime.json, /api/schedule,
     /api/runs, /api/analytics (Umami-Proxy).
   ================================================================ */
const COLORS={running:'#ff2e9e',ok:'#5bd9a0',idle:'#8a8a96',waiting:'#e6c766',error:'#f4707f'};
/* Cleane, reduzierte Chart-/Serien-Palette (Violett/Blau/Teal statt Regenbogen) */
const CHART_PAL=['#ff2e9e','#54c8e0','#5bd9a0','#ff74c4','#6d8bff','#8f9bd0'];
const LABELS={running:'running',ok:'done',idle:'ready',waiting:'waiting for you',error:'error'};
const RM=matchMedia('(prefers-reduced-motion:reduce)').matches;
const MOBILE=matchMedia('(max-width:900px)').matches;
const FORCE_DEMO=/[?&]demo\b/.test(location.search);

/* ===== Quelle der Wahrheit: Kategorien + Agents (steuert die Canvas-Welt) ===== */
const CATEGORIES=[
 {id:'monitoring',label:'MONITORING',    accent:'#5bd9a0',tint:'#233b45',light:'rgba(110,240,220,.09)'},
 {id:'content',   label:'CONTENT-STUDIO',accent:'#ff74c4',tint:'#332f52',light:'rgba(200,150,255,.10)'},
 {id:'finance',   label:'FINANZEN',      accent:'#e6c766',tint:'#3b3550',light:'rgba(255,205,110,.09)'},
 {id:'office',    label:'BÜRO',          accent:'#7cc4ff',tint:'#233848',light:'rgba(90,200,255,.09)'}
];
const AGENTS_CFG=[
 {id:'wochenreport',      name:'Wochenreport',        short:'REPORT',   cat:'content',   accent:'#ff2e9e',root:'reports',   icon:'📊',role:'Analytics & Reports'},
 {id:'content-recherche', name:'Content-Recherche',   short:'CONTENT',  cat:'content',   accent:'#ff74c4',root:'content',   icon:'✦', role:'Content-Planung'},
 {id:'video-producent',   name:'Video-Produzent',     short:'VIDEO',    cat:'content',   accent:'#6d8bff',root:'video',     icon:'🎬',role:'Video-Produktion'},
 {id:'ki-influencer',     name:'KI-Influencer',       short:'INFLU',    cat:'content',   accent:'#d46bff',root:'influencer',icon:'🤖',role:'Social-Content'},
 {id:'belege-buchhaltung',name:'Belege & Buchhaltung',short:'FINANZ',   cat:'finance',   accent:'#5bd9a0',root:'belege',    icon:'🧾',role:'Buchhaltung'},
 {id:'rechnungssteller',  name:'Rechnungssteller',    short:'RECHNUNG', cat:'finance',   accent:'#6fd0b0',root:'rechnungen',icon:'💶',role:'Rechnungen'},
 {id:'uptime-waechter',   name:'Uptime-Wächter',      short:'UPTIME',   cat:'monitoring',accent:'#5bd9a0',root:'uptime',    icon:'🛡️',role:'Uptime-Monitoring'},
 {id:'seo-audit',         name:'SEO-Audit',           short:'SEO',      cat:'monitoring',accent:'#7cc4ff',root:'seo',       icon:'🔎',role:'SEO-Audit'},
 {id:'server-waechter',   name:'Server-Wächter',      short:'SERVER',   cat:'monitoring',accent:'#8f9bd0',root:'server',    icon:'🐧',role:'Linux server monitoring'},
 {id:'mail-assistent',    name:'Mail-Assistent',      short:'MAIL',     cat:'office',    accent:'#54c8e0',root:'mail',      icon:'✉️',role:'Inbox-Triage'}
];
const MASTER_ACCENT='#ff5ca8';
const FLEET_IDS=AGENTS_CFG.map(a=>a.id);
const BOT_IDS=['master',...FLEET_IDS];
const NAME_OF=Object.fromEntries([['master','MASTER'],...AGENTS_CFG.map(a=>[a.id,a.short])]);
const CFG_NAME=Object.fromEntries(AGENTS_CFG.map(a=>[a.id,a.name]));
const CFG=Object.fromEntries(AGENTS_CFG.map(a=>[a.id,a]));
const ROOT_OF=Object.fromEntries([['master','master'],...AGENTS_CFG.map(a=>[a.id,a.root])]);
const META=id=>id==='master'?{icon:'🧠',role:'Mission orchestration',accent:MASTER_ACCENT}:CFG[id]||{icon:'◉',role:'',accent:'#8ea0bd'};

/* ===== Laufzeit-Zustand ===== */
let DATA=null,SEL=null,API=false,UPTIME=null,SCHEDULE=null,ANALYTICS=null,RUNCOUNT={},SERVER=null;
let VIEW='overview',booted=false,theatreOn=false,builtAuto=false,placeNavActive=()=>{},RANGE='7d';

/* ===== Mini-Helfer ===== */
const $=(s,r=document)=>r.querySelector(s);
const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const dstr=d=>typeof d==='string'?d:(d&&typeof d==='object'
 ?Object.entries(d).map(([k,v])=>k+': '+(v==null?'–':(typeof v==='object'?JSON.stringify(v):v))).join(', '):String(d));
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const fmtClock=iso=>{const d=new Date(iso);return isNaN(d)?'':d.toLocaleTimeString('de-AT',{hour:'2-digit',minute:'2-digit'});};
const fmtStamp=iso=>{const d=new Date(iso);return isNaN(d)?String(iso||'–'):d.toLocaleString('de-AT',{weekday:'short',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});};
function relTime(iso){const d=new Date(iso);if(isNaN(d))return '';const s=(Date.now()-d.getTime())/1000;
 if(s<60)return 'gerade eben';if(s<3600)return 'vor '+Math.round(s/60)+' Min.';if(s<86400)return 'vor '+Math.round(s/3600)+' Std.';return 'vor '+Math.round(s/86400)+' Tg.';}
function num(n){return (n==null||isNaN(n))?'–':new Intl.NumberFormat('de-AT').format(n);}
function pct(n){return n==null?'':(n>0?'+':'')+n+'%';}
function chgClass(n){return n==null?'flat':(n>0?'up':(n<0?'down':'flat'));}

/* Fehler sichtbar machen statt still sterben */
function toast(title,text,kind){
 const c=$('#toastContainer');if(!c)return;
 const t=document.createElement('div');t.className='toast'+(kind?' '+kind:'');
 t.innerHTML=`<i>${kind==='err'?'!':'✓'}</i><div><strong>${esc(title)}</strong><p>${esc(text||'')}</p></div>`;
 c.appendChild(t);setTimeout(()=>t.remove(),4200);
}
window.addEventListener('error',ev=>{try{toast('Dashboard error',ev.message||'unbekannt','err');}catch(_){}});
window.addEventListener('unhandledrejection',ev=>{const r=ev.reason;try{toast('Dashboard error',(r&&(r.message||String(r)))||'unbekannt','err');}catch(_){}});

/* ===== Demo-Fallback (nur ohne echten Server / ?demo) ===== */
const DEMO={updated:new Date().toISOString(),agents:{
 'uptime-waechter':{name:'Uptime-Wächter',status:'ok',phase:'Check abgeschlossen',progress:100,message:'3 Sites geprüft: alle ok',last_run:new Date().toISOString(),next_run:'alle 60 min',details:['naschberger.info: 200, 241ms, SSL 62 T'],outputs:[],log_tail:'Alle Sites OK'},
 'wochenreport':{name:'Wochenreport',status:'running',phase:'Analytics laden',progress:45,message:'Umami-Daten für 3 Kunden…',last_run:new Date().toISOString(),next_run:'Fr 08:00',details:[],outputs:[],log_tail:'kunde2: pageviews ok…'},
 'seo-audit':{name:'SEO-Audit',status:'waiting',phase:'Rückfrage',progress:60,message:'1 Sitemap unklar – dein Go?',last_run:new Date().toISOString(),next_run:'Mi 06:00',details:[],outputs:[],log_tail:'title zu lang'}
}};
const DEMO_UPTIME=(()=>{const names=['naschberger.info','sicherrestaurant.at','ursulakircher.at'];
 const base={'naschberger.info':241,'sicherrestaurant.at':318,'ursulakircher.at':293},ssl={'naschberger.info':62,'sicherrestaurant.at':34,'ursulakircher.at':40};
 const history=[];for(let i=23;i>=0;i--){history.push({t:'2026-07-09T'+String(i%24).padStart(2,'0')+':00:00+02:00',
  p:names.map((n,k)=>{const j=[27,53,25,41,13,67,39][(i+k)%7]-30;return {n,ms:Math.max(60,base[n]+j+k*8),ssl:ssl[n],up:1};})});}
 return {stand:'2026-07-09T21:24:48+02:00',sites:names.map(n=>({name:n,url:'https://'+n,state:'ok',http:200,ms:base[n],ssl_days:ssl[n]})),history};})();

/* ================================================================
   CANVAS-WELT (portiert aus der bisherigen index.html – unverändert)
   ================================================================ */
const U=32;
const WS_COLS=4;            // Arbeitsplätze pro Reihe in einem Themen-Pod
const CELL_W=4, CELL_H=3;   // Kachel-Fußabdruck eines Arbeitsplatzes
const GAP=1, MARGIN=1, CORR=3;

function darken(hex,d){const n=parseInt(hex.slice(1),16);
 const r=Math.max(0,(n>>16)-d),g=Math.max(0,((n>>8)&255)-d),b=Math.max(0,(n&255)-d);
 return '#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join('');}
function roomDims(n){
 const cols=Math.min(WS_COLS,Math.max(1,n)), rows=Math.ceil(Math.max(1,n)/cols);
 const iw=Math.max(6,cols*CELL_W), ih=2+rows*CELL_H+1; // +2 Feature-Screen, +1 Puffer
 return {cols,rows,iw,ih,ow:iw+2,oh:ih+2};
}

const rooms=[];
for(const c of CATEGORIES){
 const agents=AGENTS_CFG.filter(a=>a.cat===c.id);
 if(!agents.length)continue;
 rooms.push({kind:'cat',label:c.label,tint:c.tint,accent:c.accent,light:c.light,agents,band:'top',...roomDims(agents.length)});
}
rooms.push({kind:'command',label:'KOMMANDO',tint:'#2c2a46',accent:MASTER_ACCENT,light:'rgba(255,120,190,.09)',
 agents:[{id:'master'}],band:'bottom',...roomDims(1)});
{const n=FLEET_IDS.length, cols=Math.min(6,Math.max(3,Math.ceil(Math.sqrt(n))+1)), rows2=Math.ceil(n/cols);
 const iw=Math.max(10,cols*3), ih=Math.max(6,rows2*2+4);
 rooms.push({kind:'lounge',label:'LOUNGE · CAFÉ',tint:'#3e3441',accent:'#ff9d5c',light:'rgba(255,170,120,.09)',
  loungeCols:cols,band:'bottom',cols,rows:rows2,iw,ih,ow:iw+2,oh:ih+2});}

/* Zwei Bänder: oben Kategorien, unten Kommando + Lounge, dazwischen Korridor */
const topBand=rooms.filter(r=>r.band==='top'), botBand=rooms.filter(r=>r.band==='bottom');
const packW=list=>list.reduce((s,r,i)=>s+r.ow+(i?GAP:0),0);
const topH=Math.max(0,...topBand.map(r=>r.oh)), botH=Math.max(0,...botBand.map(r=>r.oh));
const bandW=Math.max(packW(topBand),packW(botBand),12);
const MW=MARGIN*2+bandW, MH=1+topH+CORR+botH+1;
const corrY0=1+topH, corrY1=corrY0+CORR-1;
function placeBand(list,alignTop,anchorRow){
 let x=MARGIN+Math.max(0,Math.floor((bandW-packW(list))/2));
 for(const r of list){r.x=x; r.y=alignTop?anchorRow:anchorRow-r.oh+1; x+=r.ow+GAP;}
}
placeBand(topBand,false,corrY0-1);   // top: Unterwand am Korridor
placeBand(botBand,true, corrY1+1);   // bottom: Oberwand am Korridor

/* Kachelgitter */
const ROWS=[];
for(let y=0;y<MH;y++)ROWS.push(new Array(MW).fill(' '));
for(const r of rooms){
 for(let y=r.y;y<r.y+r.oh;y++)for(let x=r.x;x<r.x+r.ow;x++)
  ROWS[y][x]=(x===r.x||x===r.x+r.ow-1||y===r.y||y===r.y+r.oh-1)?'#':'.';
 const dx=r.x+Math.floor(r.ow/2)-1, dy=(r.band==='top')?r.y+r.oh-1:r.y;
 ROWS[dy][dx]='D';ROWS[dy][dx+1]='D';
 r.doorX=dx; r.doorY=dy;
}
for(let y=corrY0;y<=corrY1;y++){
 for(let x=MARGIN;x<MARGIN+bandW;x++)ROWS[y][x]='-';
 ROWS[y][MARGIN-1]='#';ROWS[y][MARGIN+bandW]='#';
}
const grid=ROWS.map(r=>r.slice());
const walk=(x,y)=>y>=0&&y<MH&&x>=0&&x<MW&&'.-D'.includes(grid[y][x]);
const block=(x,y)=>{grid[y][x]='#';};

/* Zonen, Labels, Spots, Möbel – alles aus den Pods */
const ROOM_LABELS=[], SPOTS={}, FURN=[], WORK={}, WAIT={}, LEISURE=[];
for(const r of rooms){
 ROOM_LABELS.push({t:r.label,x:r.x+r.ow/2,y:r.y+.3,accent:r.accent});
 FURN.push({t:'screen',x:r.x+1,y:r.y+1,w:r.iw,accent:r.accent}); // Feature-Screen (nicht blockierend)
 if(r.kind==='command'){
  const cx=r.x+Math.floor(r.ow/2), cy=r.y+r.oh-2;
  SPOTS.command={x:cx,y:cy,face:'up'};
  FURN.push({t:'console',x:cx-1,y:cy-1,w:3,accent:r.accent,nb:true});
  WORK.master='command'; WAIT.master='command';
 }else if(r.kind==='lounge'){
  for(let i=0;i<FLEET_IDS.length;i++){
   const cx=r.x+2+(i%r.loungeCols)*2, cy=r.y+2+Math.floor(i/r.loungeCols)*2, nm='leisure'+i;
   SPOTS[nm]={x:cx,y:cy,face:'down'};
   LEISURE.push(nm);
  }
  FURN.push({t:'coffeemachine',x:r.x+1,y:r.y+1});
  FURN.push({t:'arcademachine',x:r.x+r.ow-3,y:r.y+1,w:2});
  FURN.push({t:'couch',x:r.x+2,y:r.y+r.oh-2,w:4});
  FURN.push({t:'plant',x:r.x+1,y:r.y+r.oh-2}); FURN.push({t:'plant',x:r.x+r.ow-2,y:r.y+r.oh-2});
 }else{
  const gx0=r.x+1, gy0=r.y+3; // eine Reihe unter dem Feature-Screen
  r.agents.forEach((a,i)=>{
   const cx=gx0+(i%r.cols)*CELL_W, cy=gy0+Math.floor(i/r.cols)*CELL_H, nm='ws_'+a.id;
   SPOTS[nm]={x:cx+1,y:cy+1,face:'up'};
   FURN.push({t:'desk',x:cx,y:cy,w:3,accent:a.accent,agent:a.id});
   WORK[a.id]=nm; WAIT[a.id]=nm;
  });
 }
}
for(const f of FURN){
 if(f.nb||f.t==='screen')continue;
 for(let dx=0;dx<(f.w||1);dx++)for(let dy=0;dy<(f.h||1);dy++)
  if(walk(f.x+dx,f.y+dy))block(f.x+dx,f.y+dy);
}

/* ================= BFS-Pfad ================= */
function findPath(sx0,sy0,tx,ty){
 if(sx0===tx&&sy0===ty)return[];
 const key=(x,y)=>y*MW+x;
 const prev=new Map();const q=[[sx0,sy0]];prev.set(key(sx0,sy0),null);
 while(q.length){
  const [x,y]=q.shift();
  if(x===tx&&y===ty){
   const path=[];let k=key(x,y);
   while(k!==null){path.push([k%MW,Math.floor(k/MW)]);k=prev.get(k);}
   path.reverse();path.shift();return path;
  }
  for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){
   const nx=x+dx,ny=y+dy;
   if(!walk(nx,ny)||prev.has(key(nx,ny)))continue;
   prev.set(key(nx,ny),key(x,y));q.push([nx,ny]);
  }
 }
 return null;
}
/* Kachelpfad -> geglättete Punktfolge (abgerundete Ecken = flüssige Wege) */
function smoothPath(tiles,start){
 const pts=[[start.x,start.y],...tiles];
 if(pts.length<3)return tiles.map(p=>({x:p[0],y:p[1]}));
 const out=[];
 for(let i=1;i<pts.length-1;i++){
  const p0=pts[i-1],p1=pts[i],p2=pts[i+1];
  const d1=[p1[0]-p0[0],p1[1]-p0[1]], d2=[p2[0]-p1[0],p2[1]-p1[1]];
  if(d1[0]===d2[0]&&d1[1]===d2[1]){out.push({x:p1[0],y:p1[1]});continue;}
  const a={x:p1[0]-d1[0]*.42,y:p1[1]-d1[1]*.42}, b={x:p1[0]+d2[0]*.42,y:p1[1]+d2[1]*.42};
  out.push(a);
  for(const t of [.3,.5,.7]){
   out.push({x:(1-t)*(1-t)*a.x+2*(1-t)*t*p1[0]+t*t*b.x,
             y:(1-t)*(1-t)*a.y+2*(1-t)*t*p1[1]+t*t*b.y});
  }
  out.push(b);
 }
 out.push({x:pts[pts.length-1][0],y:pts[pts.length-1][1]});
 return out;
}

/* ================= Projektion (Top-down) ================= */
const WORLD_W=MW*U, WORLD_H=MH*U;
function P(cx,cy){return [cx*U,cy*U];}
function isoC(tx,ty){return [tx*U+U/2,ty*U+U/2];}  // Kachelzentrum
function rr(c,x,y,w,h,r){c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath();}

/* ================= Canvas + Kamera (weich geführt) ================= */
const cv=$('#game'),ctx=cv.getContext('2d');
ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';
const staticCv=document.createElement('canvas');staticCv.width=WORLD_W;staticCv.height=WORLD_H;
const sx=staticCv.getContext('2d');sx.imageSmoothingEnabled=true;

let camMin=Math.min(cv.width/WORLD_W,cv.height/WORLD_H);
const cam={x:WORLD_W/2,y:WORLD_H/2,scale:Math.max(camMin,1),tx:0,ty:0};
const camT={x:cam.x,y:cam.y,scale:cam.scale};   // Ziel – Kamera gleitet hin
/* Canvas füllt die Bühne; Auflösung folgt der Anzeigegröße (scharf via DPR) */
function fitCanvas(){
 const r=cv.getBoundingClientRect();
 if(!r.width||!r.height)return;
 const dpr=Math.min(1.5,window.devicePixelRatio||1);
 const w=Math.round(r.width*dpr), h=Math.round(r.height*dpr);
 if(cv.width===w&&cv.height===h)return;
 cv.width=w;cv.height=h;
 ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';
 camMin=Math.min(cv.width/WORLD_W,cv.height/WORLD_H);
 clampObj(camT);clampCam();
}
function clampObj(c){
 c.scale=Math.max(camMin,Math.min(3.5,c.scale));
 const vw=cv.width/c.scale, vh=cv.height/c.scale;
 c.x=vw>=WORLD_W?WORLD_W/2:Math.max(vw/2,Math.min(WORLD_W-vw/2,c.x));
 c.y=vh>=WORLD_H?WORLD_H/2:Math.max(vh/2,Math.min(WORLD_H-vh/2,c.y));
}
function clampCam(){
 clampObj(cam);
 cam.tx=cv.width/2-cam.x*cam.scale; cam.ty=cv.height/2-cam.y*cam.scale;
}
function camTick(dt){
 const k=RM?1:Math.min(1,1-Math.exp(-dt*7));
 cam.scale+=(camT.scale-cam.scale)*k;
 cam.x+=(camT.x-cam.x)*k; cam.y+=(camT.y-cam.y)*k;
 clampCam();
}
function camFit(){camT.scale=camMin;camT.x=WORLD_W/2;camT.y=WORLD_H/2;clampObj(camT);}

const PAL={space:'#050505',cyan:'#54e2ff',green:'#46e6a3',amber:'#f8d45c',red:'#ff6b7d',violet:'#ff2e9e'};
function hexA(h,a){const n=parseInt(h.slice(1),16);return 'rgba('+(n>>16)+','+((n>>8)&255)+','+(n&255)+','+a+')';}
function lite(h,d){const n=parseInt(h.slice(1),16);
 const r=Math.min(255,(n>>16)+d),g=Math.min(255,((n>>8)&255)+d),b=Math.min(255,(n&255)+d);
 return '#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join('');}
function hash(x,y){let h=(x*374761393+y*668265263)|0;h=(h^(h>>13))*1274126177;return ((h^(h>>16))>>>0)/4294967295;}
function isFloor(x,y){return ROWS[y]&&'.-D'.includes(ROWS[y][x]);}
function grad(c,x0,y0,x1,y1,stops){const g=c.createLinearGradient(x0,y0,x1,y1);for(const[o,cc]of stops)g.addColorStop(o,cc);return g;}
function softShadow(cx,cy,rx,ry,a){const g=sx.createRadialGradient(cx,cy,1,cx,cy,Math.max(rx,ry));
 g.addColorStop(0,'rgba(2,3,8,'+(a||.5)+')');g.addColorStop(1,'rgba(2,3,8,0)');
 sx.fillStyle=g;sx.beginPath();sx.ellipse(cx,cy,rx,ry,0,0,7);sx.fill();}
function furnCenter(f){return P(f.x+(f.w||1)/2,f.y+(f.h||1)/2);}

/* ================= Statische Ebene: Holo-Station =================
 Klarer Blueprint-Look: dunkler Raum, Basisplatte, angedockte Pods mit
 Leuchtkante, Korridor-Röhre, Schleusen-Stege. Keine Pseudo-3D-Wände. */
function drawStatic(){
 sx.textAlign='left';
 sx.clearRect(0,0,WORLD_W,WORLD_H);   // Weltraum kommt full-bleed im Screen-Space (draw)

 // --- Basisplatte der Station ---
 const minX=Math.min(...rooms.map(r=>r.x)), maxX=Math.max(...rooms.map(r=>r.x+r.ow));
 const minY=Math.min(...rooms.map(r=>r.y)), maxY=Math.max(...rooms.map(r=>r.y+r.oh));
 sx.save();
 sx.shadowColor='rgba(90,140,255,.22)';sx.shadowBlur=60;
 rr(sx,(minX-.55)*U,(minY-.55)*U,(maxX-minX+1.1)*U,(maxY-minY+1.1)*U,30);
 sx.fillStyle='rgba(9,12,26,.6)';sx.fill();
 sx.restore();
 sx.strokeStyle='rgba(150,175,230,.09)';sx.lineWidth=1.5;
 rr(sx,(minX-.55)*U,(minY-.55)*U,(maxX-minX+1.1)*U,(maxY-minY+1.1)*U,30);sx.stroke();

 // --- Korridor-Röhre ---
 {const X0=MARGIN*U+3,Y0=corrY0*U+3,W=bandW*U-6,H=CORR*U-6;
  rr(sx,X0,Y0,W,H,12);
  sx.fillStyle=grad(sx,0,Y0,0,Y0+H,[[0,'#181f3b'],[.5,'#131a33'],[1,'#101528']]);sx.fill();
  sx.strokeStyle=hexA(PAL.cyan,.18);sx.lineWidth=1.5;sx.stroke();
  // Mittellinie
  sx.save();sx.setLineDash([12,16]);sx.strokeStyle='rgba(120,170,255,.14)';sx.lineWidth=2;
  sx.beginPath();sx.moveTo(X0+14,Y0+H/2);sx.lineTo(X0+W-14,Y0+H/2);sx.stroke();sx.restore();
  // Randmarkierungen
  sx.fillStyle='rgba(120,160,255,.08)';
  for(let x=MARGIN+1;x<MARGIN+bandW-1;x+=2){sx.fillRect(x*U+8,Y0+4,U-16,2);sx.fillRect(x*U+8,Y0+H-6,U-16,2);}
 }

 // --- Pods (Räume) ---
 for(const r of rooms){
  const px0=(r.x+.3)*U, py0=(r.y+.3)*U, pw=(r.ow-.6)*U, ph=(r.oh-.6)*U, rad=15;
  // Boden
  rr(sx,px0,py0,pw,ph,rad);
  sx.fillStyle=grad(sx,0,py0,0,py0+ph,[[0,lite(r.tint,10)],[1,darken(r.tint,14)]]);sx.fill();
  // Nähte + Glanz + Rand-AO (geclippt)
  sx.save();rr(sx,px0,py0,pw,ph,rad);sx.clip();
  sx.strokeStyle='rgba(255,255,255,.035)';sx.lineWidth=1;
  for(let x=r.x+1;x<r.x+r.ow;x++){sx.beginPath();sx.moveTo(x*U+.5,py0);sx.lineTo(x*U+.5,py0+ph);sx.stroke();}
  for(let y=r.y+1;y<r.y+r.oh;y++){sx.beginPath();sx.moveTo(px0,y*U+.5);sx.lineTo(px0+pw,y*U+.5);sx.stroke();}
  sx.fillStyle=grad(sx,px0,py0,px0+pw*.8,py0+ph*.8,[[0,'rgba(255,255,255,.05)'],[.5,'rgba(255,255,255,0)']]);
  sx.fillRect(px0,py0,pw,ph);
  const ao=sx.createRadialGradient(px0+pw/2,py0+ph/2,Math.min(pw,ph)*.28,px0+pw/2,py0+ph/2,Math.max(pw,ph)*.7);
  ao.addColorStop(0,'rgba(0,0,0,0)');ao.addColorStop(1,'rgba(2,4,10,.42)');
  sx.fillStyle=ao;sx.fillRect(px0,py0,pw,ph);
  sx.restore();
  // Leuchtkante (einmal weich, einmal scharf)
  sx.save();
  sx.strokeStyle=hexA(r.accent,.5);sx.lineWidth=1.6;sx.shadowColor=r.accent;sx.shadowBlur=14;
  rr(sx,px0,py0,pw,ph,rad);sx.stroke();
  sx.shadowBlur=0;sx.strokeStyle=hexA(r.accent,.7);sx.lineWidth=1;
  rr(sx,px0,py0,pw,ph,rad);sx.stroke();
  sx.restore();
 }

 // --- Schleusen-Stege (Pod <-> Korridor) ---
 for(const r of rooms){
  const dx=r.doorX;
  const x0=dx*U+2, w=2*U-4;
  let y0,h;
  if(r.band==='top'){y0=(r.y+r.oh-.55)*U; h=corrY0*U+8-y0;}
  else{y0=(corrY1+1)*U-8; h=(r.y+.55)*U-y0;}
  rr(sx,x0,y0,w,h,6);
  sx.fillStyle='#161d36';sx.fill();
  sx.strokeStyle=hexA(r.accent,.3);sx.lineWidth=1;sx.stroke();
  // Schwelle glüht
  const gy=r.band==='top'?(r.y+r.oh-.5)*U:(r.y+.5)*U-2;
  sx.fillStyle=hexA(PAL.cyan,.4);sx.shadowColor=PAL.cyan;sx.shadowBlur=9;
  sx.fillRect(x0+6,gy,w-12,2.5);sx.shadowBlur=0;
 }

 // --- Möbel ---
 for(const f of FURN)drawFurnStatic(f);
 // Gate-Chevrons vor jeder Agent-Station
 for(const id of FLEET_IDS){const sp=SPOTS[WORK[id]];if(!sp)continue;
  const px=sp.x*U+U/2, py=sp.y*U+U/2, ac=(ACCENT[id]||PAL.cyan);
  sx.save();sx.strokeStyle=hexA(ac,.4);sx.lineWidth=1.3;
  for(let i=0;i<3;i++){sx.globalAlpha=.4-i*.11;sx.beginPath();
   sx.moveTo(px-6,py+14+i*5);sx.lineTo(px,py+9+i*5);sx.lineTo(px+6,py+14+i*5);sx.stroke();}
  sx.restore();}
 sx.globalAlpha=1;

 // --- Pod-Labels (Holo-Tags auf der Oberkante) ---
 for(const r of ROOM_LABELS){
  sx.font='600 11px system-ui,sans-serif';
  const tw=sx.measureText(r.t).width, cx=r.x*U, x0=cx-(tw+26)/2, y0=r.y*U-9;
  rr(sx,x0,y0,tw+26,18,9);sx.fillStyle='rgba(8,12,24,.88)';sx.fill();
  sx.strokeStyle='rgba(120,140,190,.3)';sx.lineWidth=1;sx.stroke();
  sx.fillStyle=r.accent;sx.shadowColor=r.accent;sx.shadowBlur=6;sx.beginPath();sx.arc(x0+12,y0+9,2.8,0,7);sx.fill();sx.shadowBlur=0;
  sx.fillStyle='#e3ecff';sx.fillText(r.t,x0+19,y0+13);
 }

}

function drawFurnStatic(f){
 const X=f.x*U,Y=f.y*U,W=(f.w||1)*U,A=f.accent||PAL.cyan;
 switch(f.t){
  case 'screen':{ // Feature-Screen oben im Pod
   rr(sx,X-2,Y+3,W+4,U-11,7);
   sx.fillStyle=grad(sx,0,Y,0,Y+U,[[0,'#0e1730'],[1,'#070c1a']]);sx.fill();
   sx.strokeStyle=hexA(A,.55);sx.lineWidth=1.4;sx.shadowColor=A;sx.shadowBlur=9;sx.stroke();sx.shadowBlur=0;break;}
  case 'desk':{softShadow(X+W/2,Y+U-3,W/2+2,7,.5);
   rr(sx,X+2,Y+6,W-4,U-10,8);
   sx.fillStyle=grad(sx,0,Y+6,0,Y+U-4,[[0,'#28324e'],[1,'#121829']]);sx.fill();
   sx.strokeStyle=hexA(A,.4);sx.lineWidth=1.3;sx.stroke();
   rr(sx,X+6,Y+9,W-12,4,2);sx.fillStyle='rgba(255,255,255,.07)';sx.fill();
   sx.fillStyle=hexA(A,.8);sx.beginPath();sx.arc(X+W-8,Y+U-9,1.7,0,7);sx.fill();break;}
  case 'coffeemachine':{softShadow(X+16,Y+U-2,14,5,.45);
   rr(sx,X+4,Y-14,24,30,6);sx.fillStyle=grad(sx,0,Y-14,0,Y+16,[[0,'#3a4262'],[1,'#1a2138']]);sx.fill();
   sx.strokeStyle='rgba(160,180,220,.2)';sx.lineWidth=1;sx.stroke();
   rr(sx,X+8,Y-6,16,9,2);sx.fillStyle='#0c1120';sx.fill();break;}
  case 'arcademachine':{softShadow(X+W/2,Y+U-2,W/2,5,.45);
   rr(sx,X+2,Y-16,W-4,U+12,6);sx.fillStyle=grad(sx,0,Y-16,0,Y+U,[[0,'#241a3e'],[1,'#120e22']]);sx.fill();
   sx.strokeStyle=hexA('#c99cff',.5);sx.lineWidth=1.3;sx.stroke();
   rr(sx,X+8,Y-9,W-16,19,3);sx.fillStyle='#0a0716';sx.fill();break;}
  case 'couch':{softShadow(X+W/2,Y+U-2,W/2+4,6,.4);
   rr(sx,X-4,Y+2,W+8,U-4,10);sx.fillStyle=grad(sx,0,Y,0,Y+U,[[0,'#3a4d8f'],[1,'#26356b']]);sx.fill();
   rr(sx,X-4,Y+2,W+8,9,7);sx.fillStyle='rgba(255,255,255,.08)';sx.fill();break;}
  case 'plant':{softShadow(X+16,Y+U-2,9,4,.4);
   rr(sx,X+9,Y+15,14,13,3);sx.fillStyle=grad(sx,0,Y+15,0,Y+28,[[0,'#4a3540'],[1,'#2e2029']]);sx.fill();
   sx.fillStyle='#3aa274';sx.shadowColor='#57e0a0';sx.shadowBlur=9;
   for(const [dx,dy,rw,rh] of [[-4,-2,6,16],[3,-8,6,20],[9,-1,6,14]]){sx.beginPath();sx.ellipse(X+13+dx,Y+8+dy,rw/2,rh/2,0,0,7);sx.fill();}
   sx.shadowBlur=0;break;}
  case 'console':{softShadow(X+W/2,Y+U+2,W/2+4,7,.5);
   rr(sx,X-2,Y+9,W+4,U-9,9);sx.fillStyle=grad(sx,0,Y+9,0,Y+U,[[0,'#1f284a'],[1,'#0d1327']]);sx.fill();
   sx.strokeStyle=hexA(A,.5);sx.lineWidth=1.4;sx.stroke();
   rr(sx,X+3,Y+12,W-6,5,2);sx.fillStyle='rgba(255,255,255,.06)';sx.fill();break;}
 }
}

/* ================= Roboter: Mascot-Droiden ================= */
const ACCENT={master:MASTER_ACCENT};
for(const a of AGENTS_CFG)ACCENT[a.id]=a.accent;
function drawBot(id,cx,cy,dir,moving,st,sel,s,act){
 const acc=ACCENT[id]||'#8ea0bd', sc=COLORS[st]||COLORS.idle, seed=BOT_IDS.indexOf(id);
 const nap=act==='nap', work=act==='work'||act==='oversee', chat=act==='chat', gaze=act==='gaze';
 const hov=nap||RM?0:(Math.sin(s*2+seed*1.7)*1.6+(moving?Math.sin(s*10+seed)*1:0));
 const floorY=cy+13, by=floorY-10+hov+(nap?4:0);
 ctx.save();
 // Bodenschatten
 ctx.globalAlpha=.4;ctx.fillStyle='#03040a';ctx.beginPath();ctx.ellipse(cx,floorY+3,11-hov*.2,4,0,0,7);ctx.fill();ctx.globalAlpha=1;
 // Status-Ring: Grundring + Zustands-Signal
 ctx.strokeStyle=sc;ctx.lineWidth=1.3;ctx.globalAlpha=.28;
 ctx.beginPath();ctx.ellipse(cx,floorY+1,13,5,0,0,7);ctx.stroke();
 if(st==='running'){const rot=s*2.6+seed;
  ctx.globalAlpha=.95;ctx.lineWidth=1.8;ctx.shadowColor=sc;ctx.shadowBlur=8;
  ctx.beginPath();ctx.ellipse(cx,floorY+1,13,5,0,rot,rot+2.1);ctx.stroke();ctx.shadowBlur=0;}
 else if(st==='waiting'){ctx.globalAlpha=.3+Math.abs(Math.sin(s*2.6+seed))*.6;ctx.lineWidth=1.8;
  ctx.shadowColor=sc;ctx.shadowBlur=7;ctx.beginPath();ctx.ellipse(cx,floorY+1,13,5,0,0,7);ctx.stroke();ctx.shadowBlur=0;}
 else if(st==='error'){ctx.globalAlpha=Math.sin(s*9+seed)>0?.9:.25;ctx.lineWidth=1.8;
  ctx.beginPath();ctx.ellipse(cx,floorY+1,13,5,0,0,7);ctx.stroke();}
 if(sel){ctx.globalAlpha=.85;ctx.strokeStyle=sc;ctx.lineWidth=1.4;ctx.shadowColor=sc;ctx.shadowBlur=10;
  ctx.beginPath();ctx.ellipse(cx,floorY+1,16.5,6.5,0,0,7);ctx.stroke();ctx.shadowBlur=0;}
 ctx.globalAlpha=1;
 // Thruster-Glow (nicht beim Schlafen)
 if(!nap){const tg=ctx.createRadialGradient(cx,by+9,1,cx,by+9,10);tg.addColorStop(0,hexA(acc,.8));tg.addColorStop(1,hexA(acc,0));
  ctx.globalAlpha=.45+(RM?0:Math.sin(s*14+seed)*.18);ctx.fillStyle=tg;ctx.beginPath();ctx.ellipse(cx,by+10,7,3.5,0,0,7);ctx.fill();ctx.globalAlpha=1;}
 // Arme
 const sw=work?Math.abs(Math.sin(s*7+seed))*3:chat?Math.sin(s*4+seed)*3:moving?Math.sin(s*10+seed)*2.2:Math.sin(s*2+seed);
 for(const sgn of [-1,1]){ctx.fillStyle='#c3ccde';
  const ay=by+2+(work?-sw:sgn*sw);ctx.beginPath();ctx.arc(cx+sgn*10,ay,2.6,0,7);ctx.fill();}
 if(act==='coffee'){ctx.fillStyle='#eef2fb';rr(ctx,cx+8,by-1,5,5,1);ctx.fill();ctx.strokeStyle='#9fb0cf';ctx.lineWidth=1;ctx.stroke();}
 // Torso
 const tw=16,th=15,tx0=cx-tw/2,ty0=by-2;
 const bg=ctx.createLinearGradient(0,ty0,0,ty0+th);bg.addColorStop(0,'#eef1f8');bg.addColorStop(.5,'#b9c2d6');bg.addColorStop(1,'#7c88a4');
 rr(ctx,tx0,ty0,tw,th,5);ctx.fillStyle=bg;ctx.fill();
 ctx.strokeStyle=acc;ctx.globalAlpha=.6;ctx.lineWidth=1.4;rr(ctx,tx0+.7,ty0+.7,tw-1.4,th-1.4,4.3);ctx.stroke();ctx.globalAlpha=1;
 ctx.fillStyle=sc;ctx.shadowColor=sc;ctx.shadowBlur=6;ctx.beginPath();ctx.arc(cx,ty0+th-5,2.1,0,7);ctx.fill();ctx.shadowBlur=0;
 // Kopf / Visier
 const hw=19,hh=13,hx=cx-hw/2,hy=by-16;
 rr(ctx,hx,hy,hw,hh,5.5);const hg=ctx.createLinearGradient(0,hy,0,hy+hh);hg.addColorStop(0,'#20293e');hg.addColorStop(1,'#0b1120');ctx.fillStyle=hg;ctx.fill();
 rr(ctx,hx+2.5,hy+2.5,hw-5,hh-5,3.5);ctx.fillStyle='#05070f';ctx.fill();
 ctx.globalAlpha=.5;ctx.strokeStyle='#aeb9d6';ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(cx-2,hy+4.5,4,Math.PI*1.1,Math.PI*1.7);ctx.stroke();ctx.globalAlpha=1;
 // Augen (blinzeln + Blickrichtung)
 const blink=Math.max(0,(Math.sin(s*1.3+seed*2.1)-0.93)/0.07), open=nap?0:1-Math.min(1,blink);
 const eoff=dir==='left'?-2.2:dir==='right'?2.2:0, ey=(dir==='up'||gaze)?-1.6:0, ea=dir==='up'?.5:1, ex=2.9;
 if(nap){ctx.strokeStyle=acc;ctx.lineWidth=1.4;ctx.globalAlpha=.85;
  for(const sgn of[-1,1]){ctx.beginPath();ctx.moveTo(cx+sgn*ex-2,hy+hh/2);ctx.lineTo(cx+sgn*ex+2,hy+hh/2);ctx.stroke();}ctx.globalAlpha=1;}
 else{ctx.fillStyle=acc;ctx.shadowColor=acc;ctx.shadowBlur=7;
  for(const sgn of[-1,1]){ctx.globalAlpha=ea;ctx.beginPath();ctx.ellipse(cx+eoff+sgn*ex,hy+hh/2+ey,1.7,1.7*open+.2,0,0,7);ctx.fill();}
  ctx.shadowBlur=0;ctx.globalAlpha=1;}
 // Antenne mit pulsierender Spitze
 ctx.strokeStyle='#9fb0cf';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(cx,hy);ctx.lineTo(cx,hy-5);ctx.stroke();
 ctx.fillStyle=acc;ctx.shadowColor=acc;ctx.shadowBlur=6;ctx.beginPath();ctx.arc(cx,hy-6,1.6+Math.sin(s*5+seed)*.4,0,7);ctx.fill();ctx.shadowBlur=0;
 ctx.restore();
}

drawStatic();
fitCanvas();
camFit();
clampObj(camT);cam.x=camT.x;cam.y=camT.y;cam.scale=camT.scale;clampCam();
if(window.ResizeObserver)new ResizeObserver(()=>fitCanvas()).observe(cv);
else window.addEventListener('resize',fitCanvas);

/* ================= Bots: Verhaltens-Engine =================
 Läuft ein Task -> Bot arbeitet an der Station. Wartet -> steht dort. Fehler ->
 Funken. Sonst lebt der Bot eine Freizeit-Schleife: Kaffee, Nap, Sterne gucken,
 Kollegen besuchen, patrouillieren, wandern, quatschen. */
const bots={};
function initBots(){
 const c=SPOTS.command||{x:Math.floor(MW/2),y:corrY0+1};
 BOT_IDS.forEach((id)=>{bots[id]={id,x:c.x,y:c.y,path:[],dir:'down',spot:null,spotName:null,moveT:0,
  act:'idle',emote:null,dwell:2000,faceAt:null,status:null,nextThink:0,moving:false};});
}
const taken={};
function freeLeisure(b){
 const o=LEISURE.filter(s=>taken[s]===undefined||taken[s]===b.id);
 const pick=o.length?o[Math.floor(Math.random()*o.length)]:LEISURE[Math.floor(Math.random()*LEISURE.length)];
 for(const k in taken)if(taken[k]===b.id)delete taken[k]; taken[pick]=b.id; return pick;
}
/* Freies Leben: [zielX, zielY, blickrichtung, aktivität, emote] */
function freeLife(b){
 const r=Math.random();
 if(r<.52){const sp=freeLeisure(b),S=SPOTS[sp];b.spotName=sp;
  const o=[['coffee','☕'],['nap','💤'],['gaze','✦'],['relax','🎧'],['relax','😌'],['relax','🎵']][Math.floor(Math.random()*6)];
  return [S.x,S.y,S.face,o[0],o[1]];}
 if(r<.72){const other=FLEET_IDS[Math.floor(Math.random()*FLEET_IDS.length)],S=SPOTS[WORK[other]]||SPOTS.command;
  const ty=isFloor(S.x,S.y+1)?S.y+1:S.y; return [S.x,ty,'up','visit','👀'];}
 if(r<.86){const tx=MARGIN+1+Math.floor(Math.random()*Math.max(1,bandW-2)); return [tx,corrY0+1,'down','patrol','📡'];}
 for(let k=0;k<8;k++){const rm=rooms[Math.floor(Math.random()*rooms.length)];
  const tx=rm.x+1+Math.floor(Math.random()*(rm.ow-2)),ty=rm.y+1+Math.floor(Math.random()*(rm.oh-2));
  if(walk(tx,ty))return [tx,ty,'down','wander','🎵'];}
 const sp=freeLeisure(b),S=SPOTS[sp];return [S.x,S.y,S.face,'relax','😌'];
}
function think(b,now){
 if(!DATA)return;
 const a=DATA.agents[b.id]||{status:'idle'}, st=a.status||'idle'; b.st=st;
 let tx,ty,face,act,emote,dwell;
 if(b.id==='master'){const S=SPOTS.command;tx=S.x;ty=S.y;face=S.face;act='oversee';emote='📊';dwell=9e9;}
 else if(st==='running'){const S=SPOTS[WORK[b.id]];tx=S.x;ty=S.y;face=S.face;act='work';emote='⌨';dwell=9e9;}
 else if(st==='waiting'){const S=SPOTS[WAIT[b.id]];tx=S.x;ty=S.y;face=S.face;act='wait';emote=null;dwell=9e9;}
 else if(st==='error'){const S=SPOTS[WORK[b.id]];tx=S.x;ty=S.y;face=S.face;act='error';emote=null;dwell=9e9;}
 else {[tx,ty,face,act,emote]=freeLife(b);dwell=3500+Math.random()*6000;}
 b.act=act;b.emote=emote;b.dwell=dwell;b.faceAt=face;
 if(!b.spawned){b.spawned=true;b.x=tx;b.y=ty;b.path=[];b.dir=face||'down';b.nextThink=now+dwell;return;}
 if(Math.round(b.x)===tx&&Math.round(b.y)===ty&&Math.hypot(b.x-tx,b.y-ty)<.2){b.path=[];if(face)b.dir=face;b.nextThink=now+dwell;return;}
 const p=findPath(Math.round(b.x),Math.round(b.y),tx,ty);
 if(p&&p.length){b.path=smoothPath(p,b);b.moveT=0;b.nextThink=9e9;}else{b.nextThink=now+dwell;}
}
const BOT_SPEED=3.2; // Kacheln/s
function updateBots(dt,now){
 for(const id of BOT_IDS){
  const b=bots[id];
  if(b.path.length){
   b.moving=true;b.moveT+=dt;
   // sanft anfahren + vor dem Ziel abbremsen
   let rem=0,px=b.x,py=b.y;
   for(const p of b.path){rem+=Math.hypot(p.x-px,p.y-py);px=p.x;py=p.y;}
   const v=RM?BOT_SPEED:BOT_SPEED*Math.min(1,.3+b.moveT*2.4)*Math.min(1,.35+rem/1.3);
   let step=v*dt;
   while(step>0&&b.path.length){
    const p=b.path[0],dx=p.x-b.x,dy=p.y-b.y,d=Math.hypot(dx,dy);
    if(d<=step){b.x=p.x;b.y=p.y;step-=d;b.path.shift();}
    else{b.x+=dx/d*step;b.y+=dy/d*step;
     b.dir=Math.abs(dx)>Math.abs(dy)?(dx>0?'right':'left'):(dy>0?'down':'up');step=0;}
   }
  }else{
   if(b.moving){b.moving=false;b.moveT=0;if(b.faceAt)b.dir=b.faceAt;b.nextThink=now+(b.dwell||3000);}
   if(DATA&&now>=b.nextThink)think(b,now);
  }
 }
 // „Quatschen": zwei freie, stehende Bots nah beieinander -> zueinander drehen
 for(const id of BOT_IDS){const b=bots[id];b.chat=false;
  if(b.moving||['work','wait','error','oversee'].includes(b.act))continue;
  for(const id2 of BOT_IDS){if(id2===id)continue;const o=bots[id2];
   if(o.moving||['work','wait','error','oversee'].includes(o.act))continue;
   if(Math.hypot(b.x-o.x,b.y-o.y)<1.8){b.chat=true;
    b.dir=Math.abs(o.x-b.x)>Math.abs(o.y-b.y)?(o.x>b.x?'right':'left'):(o.y>b.y?'down':'up');break;}}
 }
}

/* ================= Partikel ================= */
const parts=[];
function spawnParts(){
 if(RM)return;
 if(parts.length>(MOBILE?45:150))return;
 const cm=FURN.find(f=>f.t==='coffeemachine');
 if(cm&&Math.random()<.06){const [cx,cy]=furnCenter(cm);
  parts.push({x:cx,y:cy-16,vx:(Math.random()-.5)*3,vy:-9-Math.random()*5,life:1.6,c:'rgba(220,230,245,.5)',s:2.4});}
 if(Math.random()<.02){const [cx,cy]=isoC(MARGIN+Math.floor(Math.random()*bandW),corrY0+Math.floor(Math.random()*CORR));
  parts.push({x:cx,y:cy,vx:2,vy:-1.5,life:4,c:'rgba(160,180,220,.25)',s:2});}
 for(const id of BOT_IDS){const b=bots[id],a=DATA&&DATA.agents[id];
  if(a&&a.status==='error'&&!b.moving&&Math.random()<.15){const [cx,cy]=isoC(b.x,b.y);
   parts.push({x:cx+(Math.random()-.5)*14,y:cy-14,vx:(Math.random()-.5)*30,vy:-20,life:.4,c:'#ffcf5c',s:2.4});}
  if(b.act==='nap'&&!b.moving&&Math.random()<.025){const [cx,cy]=isoC(b.x,b.y);
   parts.push({x:cx+7,y:cy-24,vx:3,vy:-5,life:1.5,c:'rgba(180,205,245,.6)',s:2});}}
}
function updateParts(dt){
 for(let i=parts.length-1;i>=0;i--){
  const p=parts[i];p.life-=dt;
  if(p.life<=0){parts.splice(i,1);continue;}
  p.x+=p.vx*dt*U/16;p.y+=p.vy*dt*U/16;
 }
}

/* ================= Shuttles: Abflug / Landung =================
 Statuswechsel eines Agenten schickt ein Shuttle: -> running = Abflug,
 running -> ok/idle = Landung, -> error = roter Abbruch. Rein dekorativ. */
const planes=[];
const EO=t=>1-Math.pow(1-t,3);
function stationXY(id){const sp=SPOTS[WORK[id]]||SPOTS.command||{x:MW/2,y:MH/2};return isoC(sp.x,sp.y);}
function spawnPlane(kind,id){
 if(RM)return;
 if(planes.length>(MOBILE?3:7))return;
 const o=stationXY(id), up=[o[0]+250,-3*U];
 const seg = kind==='land' ? {a:up,b:o} : {a:[o[0],o[1]],b:up};
 const ang=Math.atan2(seg.b[1]-seg.a[1],seg.b[0]-seg.a[0]);
 planes.push({kind,id,t:0,dur:kind==='land'?2.4:kind==='abort'?1.8:2.6,seg,ang,accent:ACCENT[id]||COLORS.running});
}
function onStatusChange(id,prev,st){
 if(st==='running')spawnPlane('takeoff',id);
 else if(prev==='running'&&(st==='ok'||st==='idle'))spawnPlane('land',id);
 else if(st==='error')spawnPlane('abort',id);
}
function updatePlanes(dt){
 for(let i=planes.length-1;i>=0;i--){const p=planes[i];p.t+=dt;
  if(p.t>=p.dur){
   if(p.kind==='land'){const o=stationXY(p.id);              // Touchdown-Staub
    for(let k=0;k<6;k++)parts.push({x:o[0]+(hash(k,p.t*7|0)-.5)*14,y:o[1]-6,vx:(hash(k,3)-.5)*20,vy:-8-hash(k,5)*6,life:.5,c:hexA(p.accent,.7),s:2});}
   planes.splice(i,1);}
 }
}
function drawPlanes(s){
 for(const p of planes){
  const t=Math.min(1,p.t/p.dur), e=EO(t), a=p.seg.a, b=p.seg.b;
  const x=a[0]+(b[0]-a[0])*e, y=a[1]+(b[1]-a[1])*e;
  let sc,al;
  if(p.kind==='land'){sc=.32+.68*e; al=t<.15?t/.15:1;}
  else{sc=1-.7*e; al=(t<.08?t/.08:1)*(t>.72?Math.max(0,(1-t)/.28):1);}
  if(p.kind==='abort'&&t>.5)al*=Math.max(0,1-(t-.5)/.5);
  al=Math.max(0,Math.min(1,al)); if(al<=0)continue;
  const col=p.kind==='abort'?COLORS.error:p.accent;
  ctx.save();ctx.globalAlpha=al;ctx.translate(x,y);ctx.rotate(p.ang);ctx.scale(sc,sc);
  const tg=ctx.createLinearGradient(-42,0,-6,0);tg.addColorStop(0,hexA(col,0));tg.addColorStop(1,hexA(col,.55));
  ctx.fillStyle=tg;ctx.beginPath();ctx.moveTo(-42,0);ctx.lineTo(-8,-2.6);ctx.lineTo(-8,2.6);ctx.closePath();ctx.fill();
  ctx.shadowColor=col;ctx.shadowBlur=10;
  ctx.fillStyle=hexA(col,.9);ctx.beginPath();
  ctx.moveTo(2,0);ctx.lineTo(-8,-9);ctx.lineTo(-4,-1);ctx.closePath();
  ctx.moveTo(2,0);ctx.lineTo(-8,9);ctx.lineTo(-4,1);ctx.closePath();ctx.fill();
  ctx.fillStyle='#eef3fb';ctx.beginPath();
  ctx.moveTo(14,0);ctx.lineTo(-7,-3.4);ctx.lineTo(-10,-1.8);ctx.lineTo(-10,1.8);ctx.lineTo(-7,3.4);ctx.closePath();ctx.fill();
  ctx.shadowBlur=0;ctx.fillStyle=col;ctx.beginPath();ctx.arc(-9,0,2.1+Math.sin(s*22)*.5,0,7);ctx.fill();
  ctx.restore();
 }
}

/* ================= Render-Loop ================= */
function shootStar(s){return {t:Math.floor(s/11)*11, x:(hash(Math.floor(s/11),8))*WORLD_W*.8, y:(hash(Math.floor(s/11),9))*WORLD_H*.4};}
/* Animierte Zusätze pro Möbel (über der statischen Basis) */
function furnAnim(f,s){
 const A=f.accent||PAL.cyan, X=f.x*U, Y=f.y*U, W=(f.w||1)*U, [cx]=furnCenter(f);
 if(f.t==='screen'){
  const n=Math.max(4,Math.floor(W/20));
  ctx.save();ctx.beginPath();ctx.rect(X,Y+5,W,U-14);ctx.clip();
  for(let i=0;i<n;i++){const h=5+Math.abs(Math.sin(s*1.4+i*1.7+f.x))*11, bx=X+5+i*(W-8)/n;
   ctx.fillStyle=i%3?hexA(A,.3):hexA(A,.8);rr(ctx,bx,Y+U-12-h,(W-8)/n-2,h,1.5);ctx.fill();}
  ctx.restore();
  ctx.fillStyle=hexA(A,.1);ctx.fillRect(X,Y+5+((s*18)%(U-16)),W,2);
 }else if(f.t==='desk'){
  // Holo-Display nur, wenn der Agent wirklich etwas zeigt (Zustand, keine Deko)
  const st=(DATA&&DATA.agents[f.agent]&&DATA.agents[f.agent].status)||'idle';
  if(st==='running'){
   const mx=cx,my=Y-19+Math.sin(s*1.6+f.x)*1.4, pw=Math.min(26,W-4);
   ctx.fillStyle=hexA(A,.07);ctx.beginPath();ctx.moveTo(cx-3,Y+4);ctx.lineTo(mx-pw/2,my+13);ctx.lineTo(mx+pw/2,my+13);ctx.lineTo(cx+3,Y+4);ctx.closePath();ctx.fill();
   rr(ctx,mx-pw/2,my,pw,13,2);ctx.fillStyle=hexA(A,.14);ctx.fill();ctx.strokeStyle=hexA(A,.6);ctx.lineWidth=1;ctx.stroke();
   ctx.strokeStyle=A;ctx.beginPath();
   for(let i=0;i<=pw-6;i+=3){const yy=my+6.5+Math.sin(s*4+i*.3+f.x)*3.5;i?ctx.lineTo(mx-pw/2+3+i,yy):ctx.moveTo(mx-pw/2+3+i,yy);}ctx.stroke();
  }else if(st==='waiting'){
   ctx.fillStyle=hexA(COLORS.waiting,.35+Math.abs(Math.sin(s*2.4))*.5);
   ctx.font='700 12px system-ui,sans-serif';ctx.textAlign='center';ctx.fillText('?',cx,Y-6);ctx.textAlign='left';
  }else if(st==='error'){
   ctx.fillStyle=hexA(COLORS.error,Math.sin(s*8)>0?.8:.25);
   ctx.font='700 11px system-ui,sans-serif';ctx.textAlign='center';ctx.fillText('!',cx,Y-6);ctx.textAlign='left';
  }
 }else if(f.t==='console'){
  const mst=(DATA&&DATA.agents.master&&DATA.agents.master.status)||'idle',col=COLORS[mst]||COLORS.idle,hy=Y-8;
  ctx.save();ctx.strokeStyle=col;ctx.shadowColor=col;ctx.shadowBlur=8;ctx.lineWidth=1.3;ctx.globalAlpha=.85;
  for(let i=0;i<3;i++){ctx.beginPath();ctx.ellipse(cx,hy,16-i*3,8-i*2,s*(1.1+i*.4),0,7);ctx.stroke();}
  ctx.shadowBlur=0;const oa=s*2;ctx.fillStyle=col;ctx.beginPath();ctx.arc(cx+Math.cos(oa)*15,hy+Math.sin(oa)*6,1.9,0,7);ctx.fill();ctx.restore();
 }else if(f.t==='arcademachine'){
  const on=Object.values(bots).some(b=>!b.moving&&['relax','coffee','gaze','nap'].includes(b.act));
  const c=['#c99cff','#53e0ff','#5df2b4'][Math.floor(s*(on?6:1.6))%3];
  ctx.fillStyle=hexA(c,on?.8:.4);rr(ctx,X+8,Y-9,W-16,19,3);ctx.fill();
 }else if(f.t==='coffeemachine'){
  ctx.fillStyle=Math.sin(s*2.4)>0?'#5df2b4':'#1f4a38';ctx.beginPath();ctx.arc(X+11,Y-9,1.6,0,7);ctx.fill();
 }
}
function drawBotFull(id,b,s){
 const a=DATA&&DATA.agents[id]||{}, st=a.status||'idle';
 const [cx,cy]=isoC(b.x,b.y), seed=BOT_IDS.indexOf(id), bob=RM?0:Math.sin(s*1.6+seed)*.5;
 const act=b.chat?'chat':b.act;
 ctx.save();ctx.translate(cx,cy);ctx.scale(1.12,1.12);ctx.translate(-cx,-cy);
 drawBot(id,cx,cy,b.dir,b.moving,st,SEL===id,s,act);
 ctx.restore();
 ctx.font='600 10px system-ui,sans-serif';ctx.textAlign='center';
 ctx.fillStyle='rgba(0,0,0,.65)';ctx.fillText(NAME_OF[id],cx,cy+22.5);
 ctx.fillStyle=hexA(COLORS[st]||COLORS.idle,.95);ctx.fillText(NAME_OF[id],cx,cy+22);
 let tag=null;
 if(st==='running')tag={t:(a.progress||0)+'%',c:COLORS.running};
 else if(st==='waiting')tag={t:'dein go?',c:COLORS.waiting,blink:true};
 else if(st==='error')tag={t:'fehler',c:COLORS.error};
 else if(b.chat)tag={t:'💬',c:'#aeb8d0',big:true};
 else if(b.emote&&!b.moving)tag={t:b.emote,c:'#aeb8d0',big:true};
 if(tag&&!(tag.blink&&Math.sin(s*5)<0&&!RM)){
  ctx.font=(tag.big?'13px ':'600 10px ')+'system-ui,sans-serif';
  const tw=ctx.measureText(tag.t).width+(tag.big?12:14), bx=cx-tw/2, by=cy-33+bob;
  rr(ctx,bx,by-13,tw,17,8);ctx.fillStyle='rgba(9,12,22,.9)';ctx.fill();
  ctx.strokeStyle=hexA(tag.c,.8);ctx.lineWidth=1;ctx.stroke();
  ctx.fillStyle='#eef2fb';ctx.fillText(tag.t,cx,by-1);
 }
 ctx.textAlign='left';
}
const NEBULAS=[[.22,.14,'rgba(64,42,118,.20)'],[.82,.3,'rgba(28,90,130,.16)'],[.5,.94,'rgba(82,42,110,.15)']];
function draw(t){
 const s=t/1000;
 // --- Weltraum full-bleed (Screen-Space; ferne Sterne bewegen sich nicht mit) ---
 ctx.setTransform(1,0,0,1,0,0);
 ctx.fillStyle=PAL.space;ctx.fillRect(0,0,cv.width,cv.height);
 for(const [nx,ny,nc] of NEBULAS){
  const g=ctx.createRadialGradient(nx*cv.width,ny*cv.height,10,nx*cv.width,ny*cv.height,cv.width*.42);
  g.addColorStop(0,nc);g.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=g;ctx.fillRect(0,0,cv.width,cv.height);}
 const starN=Math.min(420,Math.round(cv.width*cv.height/5600));
 for(let i=0;i<starN;i++){
  const x=hash(i,1)*cv.width,y=hash(i,2)*cv.height,r=hash(i,5)>.93?1.6:.8;
  const tw=RM?1:(.72+Math.sin(s*1.2+i)*.28);
  ctx.globalAlpha=(.28+hash(i,3)*.55)*tw;
  ctx.fillStyle=hash(i,4)>.85?'#bfe0ff':'#eef3ff';ctx.beginPath();ctx.arc(x,y,r,0,7);ctx.fill();}
 ctx.globalAlpha=1;
 if(!RM){const st2=shootStar(s),k=(s-st2.t)/1.2;
  if(k<1){const sxp=st2.x/WORLD_W*cv.width,syp=st2.y/WORLD_H*cv.height;
   ctx.strokeStyle=`rgba(200,225,255,${(1-k)*.9})`;ctx.lineWidth=1.5;
   ctx.beginPath();ctx.moveTo(sxp+k*160,syp+k*70);ctx.lineTo(sxp+k*160-22,syp+k*70-10);ctx.stroke();}}
 // --- Welt ---
 ctx.setTransform(cam.scale,0,0,cam.scale,cam.tx,cam.ty);ctx.imageSmoothingEnabled=true;
 ctx.drawImage(staticCv,0,0);
 if(!RM){
  // Datenstrom im Korridor
  ctx.fillStyle=hexA(PAL.cyan,.7);ctx.shadowColor=PAL.cyan;ctx.shadowBlur=6;
  for(let i=0;i<Math.max(8,bandW);i++){const [px,py]=isoC(MARGIN+((s*3+i*1.7)%bandW),corrY0+CORR/2-.5);
   ctx.globalAlpha=.3+Math.sin(s*3+i)*.25;ctx.beginPath();ctx.arc(px,py,1.8,0,7);ctx.fill();}
  ctx.shadowBlur=0;ctx.globalAlpha=1;
 }
 // Möbel-Animationen
 for(const f of FURN)furnAnim(f,s);
 // Bots nach y sortiert (untere verdecken obere)
 const order=[...BOT_IDS].sort((a,b2)=>bots[a].y-bots[b2].y);
 for(const id of order)drawBotFull(id,bots[id],s);
 // Partikel + Shuttles
 for(const p of parts){ctx.globalAlpha=Math.max(0,Math.min(1,p.life));ctx.fillStyle=p.c;ctx.beginPath();ctx.arc(p.x,p.y,p.s*.7,0,7);ctx.fill();}
 ctx.globalAlpha=1;
 drawPlanes(s);
 // Nachricht des gewählten Agenten
 if(SEL&&DATA){const a=DATA.agents[SEL],b=bots[SEL];if(a&&a.message&&b){const [X,Y]=isoC(b.x,b.y);
  ctx.font='12px ui-monospace,Consolas,monospace';ctx.textAlign='left';
  const msg=a.message.length>42?a.message.slice(0,41)+'…':a.message, tw=ctx.measureText(msg).width+16;
  const bx=Math.max(6,Math.min(WORLD_W-tw-6,X-tw/2)), by=Y-54;
  rr(ctx,bx,by-16,tw,22,5);ctx.fillStyle='rgba(10,13,24,.93)';ctx.fill();ctx.strokeStyle='#4b5b8a';ctx.lineWidth=1;ctx.stroke();
  ctx.fillStyle='#e8edf7';ctx.fillText(msg,bx+8,by-1);
  ctx.fillStyle='rgba(10,13,24,.93)';ctx.beginPath();ctx.moveTo(X-5,by+6);ctx.lineTo(X+5,by+6);ctx.lineTo(X,by+13);ctx.fill();}}
 // --- Vignette (Screen-Space, fokussiert die Mitte) ---
 ctx.setTransform(1,0,0,1,0,0);
 const vg=ctx.createRadialGradient(cv.width/2,cv.height/2,Math.min(cv.width,cv.height)*.42,cv.width/2,cv.height/2,Math.max(cv.width,cv.height)*.78);
 vg.addColorStop(0,'rgba(3,5,12,0)');vg.addColorStop(1,'rgba(3,5,12,.5)');
 ctx.fillStyle=vg;ctx.fillRect(0,0,cv.width,cv.height);
}

let lastT=0;
function loop(t){
 const dt=Math.min(.06,(t-lastT)/1000);lastT=t;
 camTick(dt);
 updateBots(dt,performance.now());
 spawnParts();updateParts(dt);updatePlanes(dt);
 draw(t);
 requestAnimationFrame(loop);
}

/* ================= Kamera-Steuerung =================
 Ziehen schwenkt (direkt), Rad zoomt weich auf den Cursor, Doppelklick zeigt
 alles, Klick ohne Ziehen wählt den nächsten Bot. Pointer-Events = Maus+Touch. */
function canvasXY(e){const r=cv.getBoundingClientRect();
 return {mx:(e.clientX-r.left)*cv.width/r.width, my:(e.clientY-r.top)*cv.height/r.height, rw:cv.width/r.width};}
function toWorld(e){const {mx,my}=canvasXY(e);return {mx,my,wx:(mx-cam.tx)/cam.scale,wy:(my-cam.ty)/cam.scale};}
let drag=null;
cv.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,cx:cam.x,cy:cam.y,moved:false};
 try{cv.setPointerCapture(e.pointerId);}catch(_){}});
cv.addEventListener('pointermove',e=>{if(!drag)return;
 const {rw}=canvasXY(e), dx=e.clientX-drag.x, dy=e.clientY-drag.y;
 if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;
 cam.x=drag.cx-dx*rw/cam.scale; cam.y=drag.cy-dy*rw/cam.scale;
 camT.x=cam.x;camT.y=cam.y;clampObj(camT);clampCam();});
cv.addEventListener('pointerup',e=>{if(drag&&!drag.moved)pickBot(e); drag=null;});
cv.addEventListener('pointercancel',()=>{drag=null;});
/* Zoom in der Karte ist deaktiviert – Mausrad scrollt die Seite normal,
   die Karte bleibt auf fester „Alles zeigen"-Skalierung. */
function pickBot(e){const {wx,wy}=toWorld(e);
 let best=null,bd=1e9;
 for(const id of BOT_IDS){const b=bots[id];const [px,py]=isoC(b.x,b.y);const d=Math.hypot(px-wx,(py-8)-wy);if(d<26&&d<bd){bd=d;best=id;}}
 if(best){select(best);}}
function centerOn(id){}


/* ================================================================
   ECHTE DATENANBINDUNG + VIEWS
   ================================================================ */

/* ===== API-Helfer ===== */
async function apiPost(url,body){
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
 const j=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(j.error||r.status);
 return j;
}
function flash(el,txt,ok){if(!el)return;el.textContent=txt;el.style.color=ok?'var(--green)':'var(--red)';setTimeout(()=>{if(el)el.textContent='';},3400);}

async function startRun(id,btn,prompt){
 if(FORCE_DEMO){const a=DATA.agents[id];if(a&&a.status!=='running'){a.status='running';a.phase='Started (demo)';a.progress=5;a.message='Simulated run…';applyData();}toast('Preview mode','No real run started.');return;}
 if(!API){toast('Server required','Starting needs the running server.js.','err');return;}
 const t=btn?btn.textContent:'';if(btn){btn.disabled=true;btn.textContent='…';}
 try{
  await apiPost('/api/run/'+id,prompt?{prompt}:undefined);
  const a=DATA.agents[id];if(a){a.status='running';a.phase='Started';a.progress=2;a.message='Getting to work…';}
  toast('Agent started',CFG_NAME[id]||id);
 }catch(err){
  toast('Start failed',String(err.message||'').includes('läuft')?'Already running.':String(err.message||err),'err');
 }
 if(btn){btn.textContent=t;btn.disabled=!API;}
 applyData();
}

/* ===== Daten laden ===== */
async function detectApi(){
 try{const r=await fetch('/api/ping');API=r.ok&&(await r.json()).api===true;}catch(e){API=false;}
 if(API){loadSchedule();loadAnalytics();loadRunCounts();}
 if(DATA)applyData();
}
async function loadSchedule(){try{const r=await fetch('/api/schedule?ts='+Date.now(),{cache:'no-store'});SCHEDULE=r.ok?await r.json():null;}catch(e){SCHEDULE=null;}builtAuto=false;if(DATA)applyData();}
async function loadAnalytics(){try{const r=await fetch('/api/analytics?'+analyticsQuery()+'&ts='+Date.now(),{cache:'no-store'});ANALYTICS=r.ok?await r.json():null;}catch(e){ANALYTICS=null;}if(DATA&&VIEW==='analytics')renderAnalytics();if(DATA&&VIEW==='overview')renderOverview();}
async function loadRunCounts(){
 try{const res=await Promise.all(FLEET_IDS.map(id=>fetch('/api/runs/'+id).then(r=>r.ok?r.json():[]).catch(()=>[])));
  RUNCOUNT={};FLEET_IDS.forEach((id,i)=>RUNCOUNT[id]=Array.isArray(res[i])?res[i].length:0);}catch(e){}
 if(DATA&&VIEW==='analytics')renderAnalytics();
}
async function load(){
 if(FORCE_DEMO){DATA=DEMO;DATA.demo=true;}
 else try{const r=await fetch('status.json?ts='+Date.now(),{cache:'no-store'});if(!r.ok)throw 0;DATA=await r.json();DATA.demo=false;}
 catch(e){DATA=DEMO;DATA.demo=true;}
 try{const ur=await fetch('uptime.json?ts='+Date.now(),{cache:'no-store'});UPTIME=ur.ok?await ur.json():null;}catch(e){UPTIME=null;}
 if((!UPTIME||!(UPTIME.sites||[]).length)&&DATA.demo)UPTIME=DEMO_UPTIME;
 try{const sr=await fetch('server.json?ts='+Date.now(),{cache:'no-store'});const sj=sr.ok?await sr.json():null;SERVER=(sj&&sj.stand)?sj:null;}catch(e){SERVER=null;}
 applyData();
 const anyRunning=Object.values(DATA.agents||{}).some(a=>a.status==='running');
 if(FORCE_DEMO)startTheatre();
 else{clearTimeout(load.t);load.t=setTimeout(load,anyRunning?5000:30000);}
}
function startTheatre(){
 if(theatreOn)return;theatreOn=true;const seq=[...FLEET_IDS];let i=0;
 setInterval(()=>{const id=seq[i%seq.length];i++;const a=DATA.agents[id];if(!a)return;
  if(a.status==='running'){a.status='ok';a.progress=100;a.message='Fertig ✓';a.phase='Abgeschlossen';}
  else{a.status='running';a.progress=8;a.message='läuft…';a.phase='Gestartet';}
  DATA.updated=new Date().toISOString();applyData();},3600);
}

/* ===== Ableitungen ===== */
function computeMaster(){
 const list=FLEET_IDS.map(id=>DATA.agents[id]).filter(Boolean);
 const cnt={running:0,ok:0,idle:0,waiting:0,error:0};
 list.forEach(a=>{cnt[a.status]=(cnt[a.status]||0)+1;});
 let status='idle';
 if(cnt.error)status='error';else if(cnt.running)status='running';
 else if(cnt.waiting)status='waiting';else if(cnt.ok&&!cnt.idle)status='ok';
 const run=list.filter(a=>a.status==='running');
 const progress=run.length?Math.round(run.reduce((s,a)=>s+(a.progress||0),0)/run.length):(status==='ok'?100:0);
 const real=DATA.agents.master||{};
 const p=[];if(cnt.running)p.push(cnt.running+' running');if(cnt.waiting)p.push(cnt.waiting+' waiting');if(cnt.error)p.push(cnt.error+' error');if(!p.length)p.push('all calm');
 DATA.agents.master={name:'Commander',status,phase:cnt.running?('coordinating '+cnt.running+' run'+(cnt.running>1?'s':'')):(cnt.waiting?'waiting for your go':cnt.error?'errors in sight':'all in view'),
  progress,message:p.join(' · '),_counts:cnt,last_run:real.last_run||null,next_run:real.next_run||'live',outputs:real.outputs||[],log_tail:real.log_tail||'(commander has not run yet)'};
}
function counts(){return (DATA&&DATA.agents.master&&DATA.agents.master._counts)||{running:0,ok:0,idle:0,waiting:0,error:0};}
function agent(id){return Object.assign({id},META(id),DATA&&DATA.agents[id]||{});}
function fleet(){return FLEET_IDS.map(agent);}
/* Zeit-/Cadence-Strings sauber & englisch darstellen (Eingabefeld bleibt roh) */
function prettyTime(str){
 if(str==null)return '—';
 let s=String(str).trim();
 if(!s||/^(on demand|auf abruf|kein termin|—|-)$/i.test(s))return 'on demand';
 s=s.replace(/\balle\b/gi,'every');
 const days={Mo:'Mon',Di:'Tue',Mi:'Wed',Do:'Thu',Fr:'Fri',Sa:'Sat',So:'Sun'};
 s=s.replace(/\b(Mo|Di|Mi|Do|Fr|Sa|So)\b/g,m=>days[m]||m).replace(/\bStd\b/gi,'h').replace(/\bTagen?\b/gi,'d');
 return s;
}
function nextRunOf(id){const s=SCHEDULE&&SCHEDULE.agents&&SCHEDULE.agents[id];const c=s&&s.cadence;return prettyTime((c&&c.trim())||(DATA.agents[id]&&DATA.agents[id].next_run)||'on demand');}
function goAgents(filter){AGENT_FILTER=filter||'all';const fb=$('#agentFilters');if(fb)fb.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x.dataset.filter===AGENT_FILTER));switchView('agents');}

/* ===== Zeitspanne: Presets (24h/7d/30d) + freie Datum-/Stunden-Auswahl ===== */
const RANGE_MS={'24h':864e5,'7d':7*864e5,'30d':30*864e5};
let RFROM=null,RTO=null;                                   // gesetzt bei RANGE==='custom'
const fmtDay=iso=>{const d=new Date(iso);return isNaN(d)?'':d.toLocaleDateString('en-GB',{day:'2-digit',month:'2-digit'});};
const fmtShort=ms=>{const d=new Date(ms);return isNaN(d)?'?':d.toLocaleDateString('en-GB',{day:'2-digit',month:'2-digit'})+' '+d.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});};
function toLocalInput(ms){const d=new Date(ms),p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes());}
function rangeWinMs(){return RANGE==='custom'?Math.max(1,RTO-RFROM):(RANGE_MS[RANGE]||RANGE_MS['7d']);}
function rangeLabel(){return RANGE==='custom'?(fmtShort(RFROM)+' – '+fmtShort(RTO)):({'24h':'Last 24 hours','7d':'Last 7 days','30d':'Last 30 days'}[RANGE]||'Range');}
function xFmt(){return rangeWinMs()<=2*864e5?fmtClock:fmtDay;}   // ≤2 Tage: Uhrzeit, sonst Datum
function histInRange(hist){
 if(RANGE==='custom')return (hist||[]).filter(p=>{const d=new Date(p.t).getTime();return isNaN(d)||(d>=RFROM&&d<=RTO);});
 const cut=Date.now()-rangeWinMs();return (hist||[]).filter(p=>{const d=new Date(p.t).getTime();return isNaN(d)||d>=cut;});
}
function rangeBtnHtml(){return `<button class="range-btn" data-rangebtn data-tip="Choose time range (presets or custom date/time)">${esc(rangeLabel())} <i>▾</i></button>`;}
function analyticsQuery(){return RANGE==='custom'?('from='+RFROM+'&to='+RTO):('range='+RANGE);}
function applyRange(){if(API)loadAnalytics();if(DATA)renderView(VIEW);}   // Analytics vom Server, Uptime client-seitig
function setRange(r){if(!RANGE_MS[r])return;RANGE=r;RFROM=RTO=null;applyRange();}
function setCustomRange(from,to){if(!from||!to||to<=from)return;RANGE='custom';RFROM=from;RTO=to;applyRange();}

/* ===== Render-Dispatch ===== */
function applyData(){try{applyDataInner();}catch(e){toast('Render-Fehler',(e&&e.stack||e&&e.message||String(e)),'err');}}
function applyDataInner(){
 DATA.agents=DATA.agents||{};
 FLEET_IDS.forEach(id=>{const a=DATA.agents[id];
  if(!a)DATA.agents[id]={name:CFG_NAME[id],status:'idle',phase:'Bereit',message:'Noch kein Lauf auf diesem Server',progress:0,next_run:'auf Abruf',details:[],outputs:[],log_tail:'(noch kein Lauf)'};
  else if(!a.name)a.name=CFG_NAME[id];});
 computeMaster();
 BOT_IDS.forEach(id=>{const b=bots[id];if(!b)return;const st=(DATA.agents[id]||{}).status||'idle';
  if(b.status!==st){const prev=b.status;b.status=st;b.nextThink=0;if(booted&&id!=='master')onStatusChange(id,prev,st);}});
 booted=true;
 renderShell();
 renderView(VIEW);
 if($('#agentModal').classList.contains('open')&&SEL)refreshDrawer();
}

/* ===== Shell: Sidebar-Badges, Topbar, Legende ===== */
function renderShell(){
 const c=counts(),active=c.running,alerts=c.waiting+c.error,sites=(UPTIME&&UPTIME.sites)||[];
 const online=sites.filter(s=>s.state!=='down'&&s.http!==0).length;
 $('#agentCountBadge').textContent=FLEET_IDS.length;
 $('#missionCountBadge').textContent=active+c.waiting+c.error;
 const enabled=SCHEDULE?FLEET_IDS.filter(id=>{const s=SCHEDULE.agents&&SCHEDULE.agents[id];return !s||s.enabled!==false;}).length:FLEET_IDS.length;
 $('#autoCountBadge').textContent=enabled;
 $('#systemCountBadge').textContent=sites.length||'–';
 $('#alertBadge').textContent=alerts;
 $('#alertBadge').style.display=alerts?'grid':'none';
 $('#miniSystems').textContent=sites.length?online+'/'+sites.length+' online':'–';
 $('#miniAgents').textContent=active+' active';
 $('#miniQueue').textContent=(active+c.waiting)+' open';
 const cap=Math.round(active/Math.max(1,FLEET_IDS.length)*100);
 $('#miniCapacity').style.width=cap+'%';
 $('#miniCapacityLabel').textContent=cap+'% of fleet active';
 const st=$('#apiState');st.textContent=DATA&&DATA.demo?'Preview (demo)':(API?'LIVE · API':'static');
 $('#livePill').textContent=API?'LIVE':'STAT';
 const wl=$('#workspaceList');
 if(wl)wl.innerHTML=(sites.length?sites:[]).map(s=>{const ok=s.state!=='down'&&s.http!==0;const col=ok?'var(--green)':'var(--red)';
  return `<button class="workspace-item ${ok?'ws-online':''}" data-openurl="${esc(s.url||('https://'+s.name))}" data-tip="${ok?'Online':'Offline'} · open ${esc(s.name)}"><span class="dot" style="background:${col};box-shadow:0 0 10px ${col}"></span>${esc(s.name)}${ok?'':' ⚠'}</button>`;}).join('')||'<small style="color:var(--muted-2);font-size:9px;padding-left:10px">no uptime data</small>';
 if(wl)wl.querySelectorAll('[data-openurl]').forEach(b=>b.addEventListener('click',()=>window.open(b.dataset.openurl,'_blank','noopener')));
 $('#mapLegend').innerHTML=['running','ok','idle','waiting','error'].map(k=>`<span><i class="legend-dot" style="background:${COLORS[k]}"></i>${LABELS[k]}</span>`).join('');
}

/* ===== View-Dispatch ===== */
function renderView(v){
 if(v==='overview')return renderOverview();
 if(v==='agents')return renderAgents();
 if(v==='missions')return renderMissions();
 if(v==='automations')return renderAutomations();
 if(v==='analytics')return renderAnalytics();
 if(v==='systems')return renderSystems();
}

/* ===== ÜBERSICHT ===== */
function renderOverview(){
 const c=counts(),f=fleet();
 const hh=new Date().getHours();
 $('#greeting').textContent=(hh<11?'Good morning':hh<18?'Good afternoon':'Good evening')+', Commander.';
 const need=c.waiting+c.error;
 $('#bannerSub').textContent=need?`${need} ${need===1?'mission needs':'missions need'} your attention.`:'All agents are calm – nothing critical.';
 const sites=(UPTIME&&UPTIME.sites)||[],online=sites.filter(s=>s.state!=='down'&&s.http!==0).length;
 const metrics=[
  {icon:'◉',value:c.running,label:'Agents active',change:FLEET_IDS.length+' total',color:'#ff2e9e',tip:'Show running agents',go:()=>goAgents('running')},
  {icon:'✓',value:c.ok,label:'Runs done',change:'recent',color:'#5bd9a0',tip:'Open mission control',go:()=>switchView('missions')},
  {icon:'?',value:c.waiting,label:'Waiting for you',change:c.waiting?'your go':'—',color:'#e6c766',down:c.waiting>0,tip:'See who is waiting and why',go:()=>goAgents('alert')},
  {icon:'!',value:c.error,label:'Errors',change:c.error?'check':'none',color:'#f4707f',down:c.error>0,tip:'See errors',go:()=>goAgents('alert')}
 ];
 $('#metricGrid').innerHTML=metrics.map((m,i)=>`<article class="metric-card is-click" data-mi="${i}" style="--metric-color:${m.color}" data-tip="${esc(m.tip)}"><div class="metric-top"><span class="metric-icon">${m.icon}</span><span class="metric-change ${m.down?'down':''}">${esc(m.change)}</span></div><strong>${m.value}</strong><p>${esc(m.label)}</p></article>`).join('');
 $$('#metricGrid .metric-card').forEach(el=>el.addEventListener('click',()=>{const m=metrics[+el.dataset.mi];if(m&&m.go)m.go();}));
 // Activity stream → click opens the agent
 const acts=f.filter(a=>a.last_run||a.status!=='idle').sort((a,b)=>new Date(b.last_run||0)-new Date(a.last_run||0)).slice(0,7);
 $('#activityList').innerHTML=acts.length?acts.map(a=>`<div class="activity-item is-click" data-agent="${a.id}"><span class="activity-icon" style="color:${COLORS[a.status]}">${a.icon}</span><div><strong>${esc(a.name)}</strong><p>${esc(a.message||a.phase||LABELS[a.status])}</p></div><time>${esc(a.last_run?relTime(a.last_run):LABELS[a.status])}</time></div>`).join(''):'<div class="data-empty">No activity recorded yet.</div>';
 $$('#activityList [data-agent]').forEach(el=>el.addEventListener('click',()=>openAgent(el.dataset.agent)));
 // Active missions → click opens the agent
 const miss=f.filter(a=>a.status==='running'||a.status==='waiting'||a.status==='error').sort((a,b)=>(b.progress||0)-(a.progress||0)).slice(0,5);
 $('#missionList').innerHTML=miss.length?miss.map(a=>{const pr=a.status==='error'?'critical':a.status==='waiting'?'high':'normal',pl=pr==='critical'?'Error':pr==='high'?'Waiting':'Running';
  return `<div class="mission-row is-click" data-agent="${a.id}"><div class="mission-head"><strong>${esc(a.name)}</strong><span class="priority ${pr}">${pl}</span></div><div class="mission-meta"><span>${esc(a.phase||'–')}</span><span>${a.progress||0}%</span></div><div class="progress"><span style="width:${clamp(a.progress||0,0,100)}%;background:${COLORS[a.status]}"></span></div></div>`;}).join(''):'<div class="data-empty">No active missions – all agents idle.</div>';
 $$('#missionList [data-agent]').forEach(el=>el.addEventListener('click',()=>openAgent(el.dataset.agent)));
 // Infrastructure health → click goes to systems / analytics
 const msVals=sites.map(s=>s.ms).filter(v=>v!=null),avgMs=msVals.length?Math.round(msVals.reduce((a,b)=>a+b,0)/msVals.length):null;
 const sslVals=sites.map(s=>s.ssl_days).filter(v=>v!=null),minSsl=sslVals.length?Math.min(...sslVals):null;
 const health=[
  {name:'Sites online',value:sites.length?online+'/'+sites.length:'–',sub:online===sites.length?'all reachable':'check',go:'systems'},
  {name:'Avg response',value:avgMs!=null?avgMs+' ms':'–',sub:avgMs!=null?(avgMs<500?'very good':avgMs<1000?'ok':'slow'):'no data',go:'systems'},
  {name:'Min. SSL',value:minSsl!=null?minSsl+' d':'–',sub:minSsl!=null?(minSsl<21?'renew soon':'valid'):'no data',go:'systems'},
  {name:'Visitors 7d',value:ANALYTICS&&ANALYTICS.configured?num(ANALYTICS.total.visitors):'–',sub:ANALYTICS&&ANALYTICS.configured?'Umami':'n/a',go:'analytics'}
 ];
 $('#healthGrid').innerHTML=health.map(h=>`<div class="health-card is-click" data-go="${h.go}" data-tip="Open ${h.go}"><div class="health-head"><span>${esc(h.name)}</span><i class="ring"></i></div><b>${esc(h.value)}</b><small>${esc(h.sub)}</small></div>`).join('');
 $$('#healthGrid [data-go]').forEach(el=>el.addEventListener('click',()=>switchView(el.dataset.go)));
 const bad=sites.some(s=>s.state==='down'||s.http===0)||(minSsl!=null&&minSsl<14);
 const warn=(minSsl!=null&&minSsl<21)||(avgMs!=null&&avgMs>1000);
 const chip=$('#healthChip');chip.textContent=bad?'Attention':warn?'Watch':'All stable';chip.className='status-chip '+(bad?'bad':warn?'warn':'good');
 // Automation timeline → click goes to automations
 const sched=fleet().map(a=>({a,next:nextRunOf(a.id)})).filter(x=>x.next&&x.next!=='on demand');
 $('#scheduleList').innerHTML=sched.length?sched.slice(0,6).map(x=>`<div class="schedule-row is-click" data-go="automations"><span class="sch-ico" style="color:${x.a.accent}">${x.a.icon}</span><div class="sch-main"><strong>${esc(x.a.name)}</strong><small>${esc(x.a.role)}</small></div><span class="sch-time">${esc(x.next)}</span></div>`).join(''):'<div class="data-empty">No scheduled runs – all on demand.</div>';
 $$('#scheduleList [data-go]').forEach(el=>el.addEventListener('click',()=>switchView(el.dataset.go)));
 // Response-time history (client-side filtered by the selected range)
 const ro=$('#rangeOverview');if(ro)ro.innerHTML=rangeBtnHtml();
 const perf=$('#perfChart');perf.style.height='auto';
 const hist=histInRange((UPTIME&&UPTIME.history)||[]);
 if(sites.length&&hist.length>1){
  const pal=CHART_PAL;
  const series=sites.map((s,i)=>({name:s.name,color:pal[i%pal.length],pts:hist.map(pt=>{const q=(pt.p||[]).find(x=>x.n===s.name);return q?q.ms:null;})}));
  const last=sites.map(s=>s.ms).filter(v=>v!=null),avg=last.length?Math.round(last.reduce((a,b)=>a+b,0)/last.length):0;
  $('#perfSummary').innerHTML=`<div><strong>${avg} ms</strong><span>avg response now</span></div><div class="trend positive">${hist.length} points</div>`;
  perf.innerHTML=svgLine(series,{h:150,times:hist.map(h=>h.t),xfmt:xFmt(),aria:'Response time per website'});
  $('#perfLegend').innerHTML=series.map(s=>`<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join('');
  hydrateCharts(perf);
 }else{$('#perfSummary').innerHTML='';$('#perfLegend').innerHTML='';perf.innerHTML='<div class="chart-empty">No data in this range yet.</div>';}
}

/* ===== AGENTEN ===== */
let AGENT_FILTER='all';
function renderAgents(){
 const q=($('#agentSearch')&&$('#agentSearch').value||'').toLowerCase();
 let list=fleet();
 if(AGENT_FILTER==='running')list=list.filter(a=>a.status==='running');
 else if(AGENT_FILTER==='idle')list=list.filter(a=>a.status==='idle'||a.status==='ok');
 else if(AGENT_FILTER==='alert')list=list.filter(a=>a.status==='waiting'||a.status==='error');
 if(q)list=list.filter(a=>(a.name+' '+a.role+' '+(a.message||'')).toLowerCase().includes(q));
 const cat=$('#agentCatalog');
 cat.innerHTML=list.length?list.map(a=>`<article class="agent-card" data-agent="${a.id}" style="--agent-color:${a.accent}"><div class="agent-card-top"><div class="agent-avatar">${a.icon}</div><div><h3>${esc(a.name)}</h3><span class="agent-role">${esc(a.role)}</span></div><span class="agent-status ${a.status}" style="background:${COLORS[a.status]};box-shadow:0 0 8px ${COLORS[a.status]}"></span></div><p>${esc(a.message||a.phase||LABELS[a.status])}</p><div class="agent-stats"><div class="agent-stat"><b style="color:${COLORS[a.status]}">${esc(LABELS[a.status])}</b><span>Status</span></div><div class="agent-stat"><b>${a.progress!=null?a.progress+'%':'–'}</b><span>Progress</span></div><div class="agent-stat"><b>${esc(nextRunOf(a.id))}</b><span>Next run</span></div></div><div class="agent-actions"><button data-run="${a.id}">▶ Start</button><button data-open="${a.id}">Details</button></div></article>`).join(''):'<div class="data-empty">No agents match this filter.</div>';
 cat.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();openAgent(b.dataset.open);}));
 cat.querySelectorAll('[data-run]').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();startRun(b.dataset.run,b);}));
 cat.querySelectorAll('.agent-card').forEach(card=>card.addEventListener('click',()=>openAgent(card.dataset.agent)));
}

/* ===== MISSION CONTROL – nach Dringlichkeit gruppiert (aus Live-Status) ===== */
function renderMissions(){
 const f=fleet();
 const needs=f.filter(a=>a.status==='waiting'||a.status==='error');
 const running=f.filter(a=>a.status==='running');
 const done=f.filter(a=>a.status==='ok');
 const upcoming=f.filter(a=>a.status==='idle'&&nextRunOf(a.id)!=='on demand');
 const onDemand=f.filter(a=>a.status==='idle'&&nextRunOf(a.id)==='on demand');
 const card=(a,extra)=>`<article class="mc-card is-click" data-agent="${a.id}" style="--agent-color:${a.accent}">
   <header><span class="mc-ico">${a.icon}</span><div class="mc-tt"><strong>${esc(a.name)}</strong><small>${esc(a.role)}</small></div>
   <span class="mc-pill" style="color:${COLORS[a.status]};border-color:${COLORS[a.status]}">${esc(LABELS[a.status])}</span></header>
   <p>${esc(a.message||a.phase||'—')}</p>${extra||''}</article>`;
 const actions=a=>`<div class="mc-actions"><button class="btn-run" data-run="${a.id}" ${API?'':'disabled'}>▶ Start</button><button class="btn-det">Details</button></div>`;
 const prog=a=>`<div class="progress"><span style="width:${clamp(a.progress||0,0,100)}%;background:${COLORS[a.status]}"></span></div>`;
 const section=(title,items,body)=>items.length?`<section class="mc-section"><div class="mc-head"><h3>${title}</h3><span class="mc-count">${items.length}</span></div><div class="mc-grid">${items.map(body).join('')}</div></section>`:'';
 let html='';
 html+=section('Needs you',needs,a=>card(a,actions(a)));
 html+=section('In progress',running,a=>card(a,prog(a)));
 html+=section('Upcoming',upcoming,a=>card(a,`<div class="mc-foot"><span>next: ${esc(nextRunOf(a.id))}</span>${actions(a)}</div>`));
 html+=section('Recently done',done,a=>card(a,`<div class="mc-foot"><span>${a.last_run?relTime(a.last_run):''}</span></div>`));
 if(onDemand.length)html+=`<section class="mc-section"><div class="mc-head"><h3>On demand</h3><span class="mc-count">${onDemand.length}</span></div><div class="mc-chips">${onDemand.map(a=>`<button class="mc-chip is-click" data-agent="${a.id}"><i style="background:${a.accent}"></i>${esc(a.name)}</button>`).join('')}</div></section>`;
 const board=$('#kanbanBoard');board.className='mc-wrap';
 board.innerHTML=html||'<div class="data-empty">Nothing to show.</div>';
 board.querySelectorAll('.btn-run').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();startRun(b.dataset.run,b);}));
 board.querySelectorAll('[data-agent]').forEach(el=>el.addEventListener('click',()=>openAgent(el.dataset.agent)));
}

/* ===== AUTOMATIONS (real schedule control, card-based) ===== */
function renderAutomations(){
 if(!builtAuto){buildScheduleTable();builtAuto=true;}
}
function buildScheduleTable(){
 const sa=(SCHEDULE&&SCHEDULE.agents)||{};
 const CAD_TIP="When it runs automatically — e.g. 'Fri 08:00', 'every 60 min', 'on demand'";
 $('#scheduleTable').innerHTML=fleet().map(a=>{const s=sa[a.id]||{},on=s.enabled!==false;
  return `<div class="auto-card" data-id="${a.id}">
   <div class="auto-top"><span class="auto-ico" style="color:${a.accent}">${a.icon}</span>
    <div class="auto-tt"><strong>${esc(a.name)}</strong><small>${esc(a.role)}</small></div>
    <label class="sw2" data-tip="Include this automation in the schedule"><input type="checkbox" class="cen" ${on?'checked':''} ${API?'':'disabled'}><i></i></label></div>
   <label class="auto-field"><span class="auto-lbl" data-tip="${esc(CAD_TIP)}">Schedule</span>
    <input class="sched-in cad" value="${esc(s.cadence!=null?s.cadence:(a.next_run||''))}" placeholder="Fri 08:00 · every 60 min · on demand" ${API?'':'disabled'} data-tip="${esc(CAD_TIP)}"></label>
   <div class="auto-flags">
    <label class="flag" data-tip="Ask in Discord before auto-starting (/yes · /no)"><input type="checkbox" class="csw" ${s.schwer?'checked':''} ${API?'':'disabled'}><span>Ask first</span></label>
    <label class="flag" data-tip="Don't post routine successes to Discord"><input type="checkbox" class="cqt" ${s.quiet?'checked':''} ${API?'':'disabled'}><span>Quiet</span></label>
    <span class="auto-status" style="color:${COLORS[a.status]}">${esc(LABELS[a.status])}${RUNCOUNT[a.id]!=null?' · '+RUNCOUNT[a.id]+' runs':''}</span>
    <button class="mini-run" data-run="${a.id}" data-tip="Run now" ${API?'':'disabled'}>▶</button>
   </div>
  </div>`;}).join('');
 $('#scheduleTable').querySelectorAll('.mini-run').forEach(b=>b.addEventListener('click',()=>startRun(b.dataset.run,b)));
 if(SCHEDULE)$('#scheduleMsg').textContent='Timezone '+(SCHEDULE.zeitzone||'Europe/Vienna');
}
async function saveSchedule(){
 if(FORCE_DEMO){flash($('#scheduleMsg'),'Preview mode: nothing saved.',false);return;}
 const btn=$('#scheduleSaveBtn');btn.disabled=true;
 const agents={};
 $('#scheduleTable').querySelectorAll('.auto-card').forEach(row=>{agents[row.dataset.id]={
  enabled:row.querySelector('.cen').checked,cadence:row.querySelector('.cad').value.trim(),
  schwer:row.querySelector('.csw').checked,quiet:row.querySelector('.cqt').checked};});
 try{const j=await apiPost('/api/schedule',{agents});SCHEDULE=j.schedule||SCHEDULE;flash($('#scheduleMsg'),'Schedule saved ✓',true);toast('Schedule saved','');}
 catch(err){flash($('#scheduleMsg'),'Error: '+err.message,false);}
 finally{btn.disabled=!API;}
}

/* ===== ANALYTICS (Umami) – per-website breakdown, multiple fields ===== */
function renderAnalytics(){
 const ar=$('#anRange');if(ar)ar.innerHTML=rangeBtnHtml();
 const a=ANALYTICS,tbl=$('#analyticsTable');
 if(!a||!a.configured){
  $('#analyticsRange').textContent='not connected';$('#analyticsRange').className='status-chip warn';
  $('#analyticsKpis').innerHTML='';
  $('#barChart').innerHTML=`<div class="chart-empty">${a&&a.reason?esc(a.reason):'Analytics not configured.'} – add the Umami credentials (UMAMI_*) on the server.</div>`;
  $('#barLegend').innerHTML='';$('#donutLegend').innerHTML='';$('#donutTotal').textContent='–';
  if(tbl)tbl.innerHTML='<div class="data-empty">No analytics data.</div>';return;
 }
 $('#analyticsRange').textContent=a.range||'7 days';$('#analyticsRange').className='status-chip good';
 const sites=a.sites||[];
 const prevPv=sites.reduce((s,x)=>s+(x.prev&&x.prev.pageviews||0),0),prevVs=sites.reduce((s,x)=>s+(x.prev&&x.prev.visitors||0),0);
 const chg=(now,prev)=>prev?Math.round((now-prev)/prev*100):null;
 const dur=sec=>sec==null?'–':Math.floor(sec/60)+':'+String(sec%60).padStart(2,'0');
 const avgBounce=sites.length?Math.round(sites.reduce((s,x)=>s+(x.bounce_rate||0),0)/sites.length):null;
 const avgDur=sites.length?Math.round(sites.reduce((s,x)=>s+(x.avg_seconds||0),0)/sites.length):null;
 const kpis=[
  {v:num(a.total.visitors),l:'Visitors',c:pct(chg(a.total.visitors,prevVs)),cc:chgClass(chg(a.total.visitors,prevVs))},
  {v:num(a.total.pageviews),l:'Pageviews',c:pct(chg(a.total.pageviews,prevPv)),cc:chgClass(chg(a.total.pageviews,prevPv))},
  {v:dur(avgDur),l:'Avg. time',c:'min',cc:'flat'},
  {v:avgBounce!=null?avgBounce+'%':'–',l:'Bounce rate',c:'',cc:'flat'}
 ];
 $('#analyticsKpis').innerHTML=kpis.map(k=>`<div class="analytics-kpi"><span>${esc(k.l)}</span><strong>${esc(k.v)}</strong><small class="chg ${k.cc}">${esc(k.c)}</small></div>`).join('');
 const maxPv=Math.max(1,...sites.map(s=>Math.max(s.pageviews,s.prev&&s.prev.pageviews||0)));
 $('#barChart').innerHTML=sites.map(s=>`<div class="bar-group"><div class="bars"><div class="bar" style="height:${Math.round((s.pageviews/maxPv)*100)}%"></div><div class="bar secondary" style="height:${Math.round(((s.prev&&s.prev.pageviews||0)/maxPv)*100)}%"></div></div><label>${esc((s.name||'').split('.')[0])}</label></div>`).join('')||'<div class="chart-empty">No websites in Umami.</div>';
 $('#barLegend').innerHTML='<span><i style="background:var(--accent)"></i>This week</span><span><i style="background:#3a3a52"></i>Last week</span>';
 const total=sites.reduce((s,x)=>s+x.pageviews,0)||1;const pal=CHART_PAL;
 let acc=0;const stops=sites.map((s,i)=>{const from=acc/total*360;acc+=s.pageviews;const to=acc/total*360;return `${pal[i%pal.length]} ${from}deg ${to}deg`;}).join(',');
 $('#donut').style.background=`conic-gradient(${stops||'#26364d 0deg 360deg'})`;
 $('#donutTotal').textContent=num(total);
 $('#donutLegend').innerHTML=sites.map((s,i)=>`<div class="donut-legend-row" style="--legend-color:${pal[i%pal.length]}"><i></i><span>${esc(s.name)}</span><b>${Math.round(s.pageviews/total*100)}%</b></div>`).join('');
 // Per-website breakdown: multiple fields per site
 if(tbl){
  const head=`<div class="atbl-head"><span>Website</span><span>Visitors</span><span>Views</span><span>Avg. time</span><span>Bounce</span><span>Trend</span></div>`;
  const rows=sites.map((s,i)=>{const cv=chg(s.pageviews,s.prev&&s.prev.pageviews);
   return `<div class="atbl-row is-click" data-openurl="https://${esc(s.name)}" data-tip="Open ${esc(s.name)}"><span class="atbl-site"><i style="background:${pal[i%pal.length]}"></i><span>${esc(s.name)}<small>${esc(s.domain||'')}</small></span></span><span>${num(s.visitors)}</span><span>${num(s.pageviews)}</span><span>${dur(s.avg_seconds)}</span><span>${s.bounce_rate!=null?s.bounce_rate+'%':'–'}</span><span class="chg ${chgClass(cv)}">${pct(cv)||'–'}</span></div>`;}).join('');
  tbl.innerHTML=head+rows;
  tbl.querySelectorAll('[data-openurl]').forEach(el=>el.addEventListener('click',()=>window.open(el.dataset.openurl,'_blank','noopener')));
 }
}

/* ===== SERVER- & BACKUP-HEALTH (aus server.json) ===== */
function meterHtml(pct,warn){const p=clamp(pct||0,0,100),w=warn||90;const col=p>=w?'var(--red)':p>=w*0.85?'var(--yellow)':'var(--green)';return `<div class="srv-meter"><span style="transform:scaleX(${(p/100).toFixed(3)});background:${col}"></span></div>`;}
function renderServerHealth(){
 const el=$('#serverHealth');if(!el)return;
 const s=SERVER;
 if(!s){
  const a=agent('server-waechter');
  el.innerHTML=`<section class="panel srv-panel"><div class="panel-header"><div><span class="eyebrow">SERVER · LINUX</span><h3>Server &amp; backups</h3></div><button class="secondary-button" id="srvRun" ${API?'':'disabled'} data-tip="Run the server watcher now">Run check</button></div>
   <div class="srv-empty">No structured server data yet.${a.message?' '+esc(a.message):''}<br><small>Run the 🐧 Server-Watcher to populate disk, memory, services, backups and SSL.</small></div>
   ${(a.details&&a.details.length)?'<ul class="srv-det">'+a.details.map(d=>'<li>'+esc(dstr(d))+'</li>').join('')+'</ul>':''}</section>`;
  const rb=$('#srvRun');if(rb)rb.addEventListener('click',e=>startRun('server-waechter',e.currentTarget));
  return;
 }
 const disk=s.disk||{},mem=s.memory||{},load=s.load||{},services=s.services||[],backups=s.backups||[],databases=s.databases||[];
 const loadWarn=load.warn||1.5,loadBad=load.per_core!=null&&load.per_core>loadWarn;
 const sslWarn=s.ssl_min_days!=null&&s.ssl_min_days<21,okBk=backups.filter(b=>b.ok).length,okDb=databases.filter(d=>d.active).length;
 el.innerHTML=`<section class="panel srv-panel">
  <div class="panel-header"><div><span class="eyebrow">SERVER · ${esc(s.os||'LINUX')}</span><h3>${esc(s.host||'Server & backups')}</h3></div>
   <div class="ph-right"><span class="status-chip ${s.state==='down'?'bad':s.state==='warn'?'warn':'good'}">${s.state==='down'?'Down':s.state==='warn'?'Watch':'Healthy'}</span><button class="secondary-button" id="srvRun" ${API?'':'disabled'} data-tip="Run the server watcher now">Run check</button></div></div>
  <div class="srv-grid">
   <div class="srv-gauge"><div class="srv-gh"><span>Disk</span><b>${disk.used_percent!=null?disk.used_percent+'%':'–'}</b></div>${meterHtml(disk.used_percent,disk.warn||85)}<small>${disk.free_gb!=null?disk.free_gb+' GB free':''}</small></div>
   <div class="srv-gauge"><div class="srv-gh"><span>Memory</span><b>${mem.used_percent!=null?mem.used_percent+'%':'–'}</b></div>${meterHtml(mem.used_percent,90)}<small>${mem.used_gb!=null?mem.used_gb+' / '+mem.total_gb+' GB':''}</small></div>
   <div class="srv-stat"><span>Load / core</span><b style="color:${loadBad?'var(--red)':'inherit'}">${load.per_core!=null?load.per_core:'–'}</b><small>warn ${loadWarn}${load.cores?' · '+load.cores+' cores':''}</small></div>
   <div class="srv-stat"><span>SSL min · uptime</span><b style="color:${sslWarn?'var(--red)':'inherit'}">${s.ssl_min_days!=null?s.ssl_min_days+' d':'–'}</b><small>${s.uptime?'up '+esc(s.uptime):''}</small></div>
  </div>
  <div class="srv-cols">
   <div class="srv-col"><div class="srv-lbl">Databases <b class="srv-bk ${databases.length&&okDb===databases.length?'ok':databases.length?'bad':''}">${databases.length?okDb+'/'+databases.length+' up':''}</b></div><div class="srv-chips">${databases.map(d=>`<span class="srv-chip ${d.active?'ok':'bad'}" data-tip="${esc((d.type||'database')+(d.latency_ms!=null?' · '+d.latency_ms+' ms':'')+(d.note?' · '+d.note:''))}"><i></i>${esc(d.name)}${d.latency_ms!=null?' · '+d.latency_ms+'ms':''}</span>`).join('')||'<small>none configured</small>'}</div></div>
   <div class="srv-col"><div class="srv-lbl">Services</div><div class="srv-chips">${services.map(v=>`<span class="srv-chip ${v.active?'ok':'bad'}"><i></i>${esc(v.name)}</span>`).join('')||'<small>–</small>'}</div></div>
   <div class="srv-col"><div class="srv-lbl">Backups <b class="srv-bk ${okBk===backups.length?'ok':'bad'}">${okBk}/${backups.length} ok</b></div><div class="srv-chips">${backups.map(b=>`<span class="srv-chip ${b.ok?'ok':'bad'}" data-tip="last ${b.age_hours}h ago · max ${b.max_hours}h">${b.ok?'✓':'⚠'} ${esc(b.name)} · ${b.age_hours}h</span>`).join('')||'<small>none configured</small>'}</div></div>
  </div>
  <div class="srv-foot">Failed SSH: ${(s.logins&&s.logins.failed_ssh)||0} · Log dir ${s.log_dir_mb!=null?s.log_dir_mb+' MB':'–'} · as of ${s.stand?fmtStamp(s.stand):'–'}</div>
  ${(s.alerts&&s.alerts.length)?'<div class="srv-alerts">'+s.alerts.map(x=>'<div class="srv-alert">⚠ '+esc(dstr(x))+'</div>').join('')+'</div>':''}
 </section>`;
 const rb=$('#srvRun');if(rb)rb.addEventListener('click',e=>startRun('server-waechter',e.currentTarget));
}

/* ===== SYSTEME (aus uptime.json) ===== */
function renderSystems(){
 renderServerHealth();
 const rs=$('#systemsRange');if(rs)rs.innerHTML=rangeBtnHtml();
 const up=UPTIME,sites=(up&&up.sites)||[],hist=histInRange((up&&up.history)||[]);
 if(!sites.length){$('#systemsGrid').innerHTML='<div class="data-empty">No uptime data yet. Start the uptime watcher.</div>';return;}
 const pal=CHART_PAL;
 const avails=[],lats=[];
 const tiles=sites.map((s,i)=>{
  const col=pal[i%pal.length];
  const rel=hist.map(pt=>(pt.p||[]).find(x=>x.n===s.name)).filter(Boolean);
  const avail=rel.length?Math.round(rel.filter(x=>x.up===1).length/rel.length*100):null;
  if(avail!=null)avails.push(avail);if(s.ms!=null)lats.push(s.ms);
  const pts=rel.map(x=>x.ms).filter(v=>v!=null);
  const down=rel.filter(x=>x.up===0).length,online=s.state!=='down'&&s.http!==0,sslWarn=s.ssl_days!=null&&s.ssl_days<21;
  const url=s.url||('https://'+s.name);
  return `<article class="system-tile is-click ${online?'online':'offline'}" data-site="${esc(s.name)}" data-url="${esc(url)}" data-tip="Open ${esc(s.name)} — click Details for stats" style="--system-color:${col}"><div class="system-head"><span class="system-logo">${esc((s.name||'?')[0].toUpperCase())}</span><div><h3>${esc(s.name)}</h3><p>${esc(url)}</p></div><span class="system-live" style="color:${online?'var(--green)':'var(--red)'}">${online?'ONLINE':'OFFLINE'}</span></div><div class="system-metrics"><div class="system-metric"><b>${avail!=null?avail+'%':'–'}</b><span>Uptime</span></div><div class="system-metric"><b>${s.ms!=null?s.ms+' ms':'–'}</b><span>Latency</span></div><div class="system-metric"><b style="color:${sslWarn?'var(--red)':'inherit'}">${s.ssl_days!=null?s.ssl_days+' d':'–'}</b><span>SSL</span></div></div><div class="system-graph">${miniGraph(pts,col)}</div><div class="system-footer"><span>${down?down+' outages · ':''}as of ${up.stand?fmtClock(up.stand):'–'}</span><button class="sys-det" data-site="${esc(s.name)}" data-tip="Show stored stats">Details →</button></div></article>`;
 }).join('');
 const online=sites.filter(s=>s.state!=='down'&&s.http!==0).length;
 const avgAvail=avails.length?Math.round(avails.reduce((a,b)=>a+b,0)/avails.length):null;
 const avgLat=lats.length?Math.round(lats.reduce((a,b)=>a+b,0)/lats.length):null;
 const minSsl=sites.map(s=>s.ssl_days).filter(v=>v!=null);
 const pv=ANALYTICS&&ANALYTICS.configured?ANALYTICS.total.pageviews:null;
 const summary=`<div class="systems-summary">
  <div class="sum-card"><b>${online}/${sites.length}</b><span>Websites online</span><small>monitored</small></div>
  <div class="sum-card"><b>${avgAvail!=null?avgAvail+'%':'–'}</b><span>Avg uptime</span><small>${hist.length} points</small></div>
  <div class="sum-card"><b>${avgLat!=null?avgLat+' ms':'–'}</b><span>Avg response</span><small>now</small></div>
  <div class="sum-card"><b>${pv!=null?num(pv):(minSsl.length?Math.min(...minSsl)+' d':'–')}</b><span>${pv!=null?'Pageviews (7d)':'Min. SSL'}</span><small>${pv!=null?'all sites':'shortest remaining'}</small></div>
 </div>`;
 $('#systemsGrid').innerHTML=summary+tiles;
 $('#systemsGrid').querySelectorAll('.system-tile').forEach(el=>el.addEventListener('click',()=>window.open(el.dataset.url,'_blank','noopener')));
 $('#systemsGrid').querySelectorAll('button.sys-det').forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();openSite(b.dataset.site);}));
}
function miniGraph(points,color){
 if(!points||points.length<2)return '<svg viewBox="0 0 220 50"></svg>';
 const w=220,h=50,min=Math.min(...points)-2,max=Math.max(...points)+2,rng=max-min||1;
 const p=points.map((v,i)=>`${i*w/(points.length-1)},${(h-(v-min)/rng*h).toFixed(1)}`).join(' ');
 return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${p}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

/* ================================================================
   INTERAKTIVE CHARTS (Antwortzeit-Linie + SSL-Balken mit Hover-Karte)
   ================================================================ */
const CHARTREG=new Map();let chartSeq=0;
function regChart(m){const id='ch'+(++chartSeq);CHARTREG.set(id,m);return id;}
function svgLine(series,o){
 o=o||{};const W=344,H=o.h||182,pl=34,pr=10,pt=12,pb=24;const times=o.times||[];
 const n=Math.max(0,...series.map(s=>s.pts.length));
 const vals=series.flatMap(s=>s.pts).filter(v=>v!=null&&!isNaN(v));
 if(n<2||vals.length<2)return '<div class="chart-empty">Collecting data – line needs 2+ points.</div>';
 /* Saubere Y-Achse: runde Grenzen + gleichmäßige Ticks (1/2/5·10^n-Schritte) */
 let lo=o.zero?0:Math.min(...vals),hi=Math.max(...vals);if(hi<=lo)hi=lo+1;
 const raw=(hi-lo)/2,mag=Math.pow(10,Math.floor(Math.log10(raw||1))),nrm=raw/mag,stepN=(nrm>=5?5:nrm>=2?2:1)*mag;
 lo=Math.floor(lo/stepN)*stepN;hi=Math.ceil(hi/stepN)*stepN;if(hi<=lo)hi=lo+stepN;
 const yv=[];for(let v=lo;v<=hi+1e-6;v+=stepN)yv.push(v);
 const Y=v=>pt+(1-(v-lo)/(hi-lo))*(H-pt-pb);
 /* X-Achse zeitlich LINEAR, wenn gültige Zeitstempel vorliegen (ungleiche Abstände korrekt) */
 const tms=times.map(t=>new Date(t).getTime()),plotW=W-pl-pr;
 const timeMode=tms.length===n&&tms.every(v=>!isNaN(v))&&tms[n-1]>tms[0];
 const t0=timeMode?tms[0]:0,t1=timeMode?tms[n-1]:1;
 const X=i=>timeMode?(pl+(tms[i]-t0)/(t1-t0)*plotW):(pl+(i/(n-1))*plotW);
 const grid=yv.map(v=>`<line class="gl" x1="${pl}" y1="${Y(v).toFixed(1)}" x2="${W-pr}" y2="${Y(v).toFixed(1)}"/><text class="gt" x="${pl-5}" y="${(Y(v)+4).toFixed(1)}" text-anchor="end">${Math.round(v)}</text>`).join('');
 const xf=o.xfmt||fmtClock;
 let xticks;
 if(timeMode){xticks=[0,1,2,3].map(k=>({x:pl+k/3*plotW,l:xf(new Date(t0+k/3*(t1-t0)).toISOString())}));}
 else{const idx=[...new Set([0,Math.round((n-1)/3),Math.round(2*(n-1)/3),n-1])].filter(i=>i>=0&&i<n);xticks=idx.map(i=>({x:X(i),l:times[i]?xf(times[i]):'#'+(i+1)}));}
 const xax=xticks.map(t=>`<text class="gt" x="${t.x.toFixed(1)}" y="${H-9}" text-anchor="middle">${esc(t.l)}</text>`).join('');
 const unit=`<text class="gt" x="${pl-5}" y="10" text-anchor="end" opacity=".85">ms</text>`;
 const lines=series.map(s=>{let d='',pen=false;s.pts.forEach((v,i)=>{if(v==null||isNaN(v)){pen=false;return;}d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)+' ';pen=true;});return d?`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`:'';}).join('');
 const dots=series.map(s=>{for(let i=s.pts.length-1;i>=0;i--){const v=s.pts[i];if(v!=null&&!isNaN(v))return `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="3" fill="${s.color}"/>`;}return '';}).join('');
 const id=regChart({type:'line',series,times,tms,timeMode,t0,t1,W,H,pl,pr,n});
 return `<div class="chartwrap" data-chart="${id}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria||'Chart')}">${grid}${unit}${xax}${lines}${dots}</svg><div class="cguide"></div><div class="ctip"></div></div>`;
}
function svgBars(rows,o){
 o=o||{};const W=344,pad=6,rowH=46,top=8,thr=o.threshold||21;
 const H=top+rows.length*rowH+2,trackW=W-pad*2;
 const max=Math.max(thr*1.5,...rows.map(r=>r.value||0),1);
 const Xw=v=>Math.max(4,(v/max)*trackW),thrX=pad+(thr/max)*trackW;
 const body=rows.map((r,i)=>{const y=top+i*rowH,v=r.value;const col=v==null?'var(--muted)':(v<thr?'var(--red)':(v<thr*2?'var(--yellow)':'var(--green)'));const barY=y+22;
  return `<text class="bl" x="${pad}" y="${y+14}">${esc(r.label)}</text><text class="bval" x="${W-pad}" y="${y+14}" text-anchor="end" fill="${col}">${v==null?'?':v+' days'}</text><rect x="${pad}" y="${barY}" width="${trackW}" height="12" rx="6" fill="rgba(255,255,255,.06)"/><rect x="${pad}" y="${barY}" width="${Xw(v||0).toFixed(1)}" height="12" rx="6" fill="${col}"/>`;}).join('');
 const id=regChart({type:'bars',rows,W,H,rowH,top,thr});
 return `<div class="chartwrap" data-chart="${id}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria||'Bars')}"><line class="thr" x1="${thrX.toFixed(1)}" y1="${top+16}" x2="${thrX.toFixed(1)}" y2="${H-2}"/><text class="thrt" x="${(thrX+4).toFixed(1)}" y="${top+8}">Threshold ${thr}</text>${body}</svg><div class="ctip"></div></div>`;
}
function hydrateCharts(root){
 if(!root||!root.querySelectorAll)return;
 root.querySelectorAll('.chartwrap[data-chart]').forEach(w=>{
  const m=CHARTREG.get(w.dataset.chart);CHARTREG.delete(w.dataset.chart);if(!m||w.__wired)return;w.__wired=true;
  const svg=w.querySelector('svg'),tip=w.querySelector('.ctip'),guide=w.querySelector('.cguide');
  w.addEventListener('pointermove',ev=>{
   const r=svg.getBoundingClientRect(),wr=w.getBoundingClientRect();if(!r.width)return;
   if(m.type==='line'){
    const vx=(ev.clientX-r.left)/r.width*m.W,plotW=m.W-m.pl-m.pr;let i;
    if(m.timeMode){const ms=m.t0+clamp((vx-m.pl)/plotW,0,1)*(m.t1-m.t0);let bd=Infinity;i=0;for(let k=0;k<m.n;k++){const d=Math.abs(m.tms[k]-ms);if(d<bd){bd=d;i=k;}}}
    else{i=clamp(Math.round((vx-m.pl)/(plotW/(m.n-1))),0,m.n-1);}
    const Xi=m.timeMode?(m.pl+(m.tms[i]-m.t0)/(m.t1-m.t0)*plotW):(m.pl+(i/(m.n-1))*plotW);
    const px=(Xi/m.W)*r.width+(r.left-wr.left);
    if(guide)guide.style.left=px.toFixed(1)+'px';
    const trs=m.series.map(s=>{const v=s.pts[i];return `<div class="tr"><span class="nm"><i style="background:${s.color}"></i>${esc(s.name)}</span><b>${v==null||isNaN(v)?'— down':v+' ms'}</b></div>`;}).join('');
    tip.innerHTML=`<div class="tt">${esc(m.times[i]?fmtStamp(m.times[i]):'Messpunkt '+(i+1))}</div>${trs}`;
    const tw=tip.offsetWidth||150;tip.style.left=clamp(px-tw/2,4,wr.width-tw-4).toFixed(1)+'px';tip.style.top='4px';
   }else{
    const vy=(ev.clientY-r.top)/r.height*m.H;let i=Math.floor((vy-m.top)/m.rowH);i=clamp(i,0,m.rows.length-1);
    const row=m.rows[i],v=row.value,st=v==null?'no data':(v<m.thr?'below threshold – renew!':(v<m.thr*2?'renew soon':'all good'));
    tip.innerHTML=`<div class="tt">${esc(row.label)}</div><div class="tr"><span class="nm">SSL expires in</span><b>${v==null?'?':v+' days'}</b></div><div class="tr"><span class="nm">Status</span><b>${esc(st)}</b></div>`;
    const tw=tip.offsetWidth||160,th=tip.offsetHeight||60,cx=ev.clientX-wr.left,cy=ev.clientY-wr.top;
    tip.style.left=clamp(cx+14,4,wr.width-tw-4).toFixed(1)+'px';tip.style.top=clamp(cy-th-10,4,wr.height-th-4).toFixed(1)+'px';
   }
   w.classList.add('hot');
  });
  w.addEventListener('pointerleave',()=>w.classList.remove('hot'));
 });
}

/* ================================================================
   DRAWER (Agent-Detail) + Auswahl aus der Karte
   ================================================================ */
function select(id){openAgent(id);}
function openAgent(id){
 SEL=id;const a=agent(id);const c=COLORS[a.status]||COLORS.idle;
 const isUptime=id==='uptime-waechter';
 let uptimeHtml='';
 if(isUptime){const up=UPTIME,sites=(up&&up.sites)||[],hist=histInRange((up&&up.history)||[]);
  if(sites.length){const pal=CHART_PAL;
   const series=sites.map((s,i)=>({name:s.name,color:pal[i%pal.length],pts:hist.map(pt=>{const q=(pt.p||[]).find(x=>x.n===s.name);return q?q.ms:null;})}));
   uptimeHtml=`<div class="drawer-section"><h4>RESPONSE TIME</h4>${svgLine(series,{zero:true,times:hist.map(h=>h.t),xfmt:xFmt(),aria:'Response time'})}</div><div class="drawer-section"><h4>SSL REMAINING</h4>${svgBars(sites.map(s=>({label:s.name,value:s.ssl_days})),{threshold:21})}</div>`;}
 }
 const outs=(a.outputs&&a.outputs.length)?'<ul style="margin:4px 0 0 16px;font-size:11px;line-height:1.6">'+a.outputs.map(o=>'<li><code>'+esc(o)+'</code></li>').join('')+'</ul>':'<p style="font-size:11px;color:var(--muted)">none yet</p>';
 const dets=(a.details&&a.details.length)?'<ul style="margin:4px 0 0 16px;font-size:11px;line-height:1.6">'+a.details.map(d=>'<li>'+esc(dstr(d))+'</li>').join('')+'</ul>':'<p style="font-size:11px;color:var(--muted)">–</p>';
 $('#drawerContent').innerHTML=`
  <div class="drawer-hero" style="--drawer-color:${a.accent}"><div class="drawer-avatar">${a.icon}</div><h2>${esc(a.name)}</h2><p>${esc(a.role)}</p><span class="drawer-status" style="color:${c}">● ${esc(LABELS[a.status]||a.status)}</span></div>
  <div class="drawer-section"><h4>CURRENT STATUS</h4><div class="drawer-task"><strong>${esc(a.phase||'–')}</strong><p>${esc(a.message||'–')}</p><div class="progress"><span style="width:${clamp(a.progress||0,0,100)}%;background:${c}"></span></div></div></div>
  <div class="drawer-section"><h4>PERFORMANCE</h4><div class="drawer-grid"><div class="drawer-stat"><b>${RUNCOUNT[id]!=null?RUNCOUNT[id]:'–'}</b><span>Runs</span></div><div class="drawer-stat"><b>${a.progress!=null?a.progress+'%':'–'}</b><span>Progress</span></div><div class="drawer-stat"><b style="font-size:12px">${esc(nextRunOf(id))}</b><span>Next</span></div></div></div>
  ${uptimeHtml}
  <div class="drawer-section"><h4>RECENT DETAILS</h4>${dets}</div>
  <div class="drawer-section"><h4>OUTPUTS</h4>${outs}</div>
  ${API?`<div class="drawer-section"><h4>LOG</h4><div class="drawer-log" id="drawerLog">…</div></div><div class="drawer-section"><h4>RECENT RUNS</h4><div class="drawer-runs" id="drawerRuns"><span style="font-size:11px;color:var(--muted)">…</span></div></div>`:''}
  <div class="drawer-actions"><button class="primary-button" id="drawerRun">▶ Start now</button><button class="secondary-button" id="drawerMission">Send order</button></div>`;
 $('#drawerRun').addEventListener('click',e=>startRun(id,e.currentTarget));
 $('#drawerMission').addEventListener('click',()=>{closeDrawer();openMissionFor(id);});
 hydrateCharts($('#drawerContent'));
 if(API){
  fetch('/api/log/'+id).then(r=>r.json()).then(d=>{const el=$('#drawerLog');if(el)el.textContent=(d&&d.text)||a.log_tail||'(empty)';}).catch(()=>{const el=$('#drawerLog');if(el)el.textContent=a.log_tail||'(empty)';});
  fetch('/api/runs/'+id).then(r=>r.json()).then(runs=>{const el=$('#drawerRuns');if(!el)return;
   if(!Array.isArray(runs)||!runs.length){el.innerHTML='<span style="font-size:11px;color:var(--muted)">no runs yet</span>';return;}
   el.innerHTML=runs.slice(0,6).map(r=>{const col=r.rc===0?(r.status==='waiting'?COLORS.waiting:COLORS.ok):COLORS.error;const t=new Date(r.t0);
    return `<div class="drawer-run"><i style="background:${col}"></i><span>${esc(r.status?(LABELS[r.status]||r.status):(r.rc===0?'done':'error'))}</span><time>${isNaN(t)?esc(r.run||''):t.toLocaleString('en-GB',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})}</time></div>`;}).join('');
  }).catch(()=>{});
 }
 openModal('agentModal');
}
function refreshDrawer(){if(!SEL)return;const a=agent(SEL);const hero=$('#drawerContent .drawer-status');if(hero){hero.style.color=COLORS[a.status]||COLORS.idle;hero.textContent='● '+(LABELS[a.status]||a.status);}}
function closeDrawer(){closeModal('agentModal');}

/* Website-Detail als Popup-Card (aus der Systemübersicht) */
function openSite(name){
 const up=UPTIME,sites=(up&&up.sites)||[],hist=histInRange((up&&up.history)||[]);
 const s=sites.find(x=>x.name===name);if(!s)return;
 const rel=hist.map(pt=>(pt.p||[]).find(x=>x.n===name)).filter(Boolean);
 const avail=rel.length?Math.round(rel.filter(x=>x.up===1).length/rel.length*100):null;
 const down=rel.filter(x=>x.up===0).length,online=s.state!=='down'&&s.http!==0;
 const msVals=rel.map(x=>x.ms).filter(v=>v!=null);
 const avg=msVals.length?Math.round(msVals.reduce((a,b)=>a+b,0)/msVals.length):null;
 const series=[{name,color:'#ff2e9e',pts:rel.map(x=>x.ms)}];
 SEL=null;
 const url=s.url||('https://'+name);
 $('#drawerContent').innerHTML=`
  <div class="drawer-hero" style="--drawer-color:#ff2e9e"><div class="drawer-avatar">${esc((name[0]||'?').toUpperCase())}</div><h2>${esc(name)}</h2><p>${esc(url)}</p><span class="drawer-status" style="color:${online?'var(--green)':'var(--red)'}">● ${online?'ONLINE & reachable':'OFFLINE'}</span></div>
  <div class="drawer-section"><h4>METRICS</h4><div class="detail-metrics">
   <div class="detail-metric"><b>${s.http||'–'}</b><span>HTTP status</span></div>
   <div class="detail-metric"><b>${s.ms!=null?s.ms+' ms':'–'}</b><span>Latency now</span></div>
   <div class="detail-metric"><b>${avail!=null?avail+'%':'–'}</b><span>Uptime</span></div>
   <div class="detail-metric"><b>${avg!=null?avg+' ms':'–'}</b><span>Avg response</span></div>
   <div class="detail-metric"><b style="color:${s.ssl_days!=null&&s.ssl_days<21?'var(--red)':'inherit'}">${s.ssl_days!=null?s.ssl_days+' days':'–'}</b><span>SSL remaining</span></div>
   <div class="detail-metric"><b>${down}</b><span>Outages (history)</span></div>
  </div></div>
  <div class="drawer-section"><h4>RESPONSE-TIME HISTORY</h4>${svgLine(series,{zero:true,times:hist.map(h=>h.t),xfmt:xFmt(),aria:'Response time '+name})}</div>
  <div class="drawer-section"><h4>SSL REMAINING</h4>${svgBars([{label:name,value:s.ssl_days}],{threshold:21})}</div>
  <div class="drawer-section"><h4>LAST CHECK</h4><p style="font-size:11px;color:var(--muted)">${up.stand?fmtStamp(up.stand):'–'}${s.reason?' · '+esc(s.reason):''}</p></div>
  <div class="drawer-actions"><button class="primary-button" id="siteOpen">Open website ↗</button></div>`;
 const ob=$('#siteOpen');if(ob)ob.addEventListener('click',()=>window.open(url,'_blank','noopener'));
 hydrateCharts($('#drawerContent'));
 openModal('agentModal');
}

/* ================================================================
   MODALS / KOMMANDANT / NAVIGATION
   ================================================================ */
function openModal(id){const el=$('#'+id);el.classList.add('open');el.setAttribute('aria-hidden','false');}
function closeModal(id){const el=$('#'+id);el.classList.remove('open');el.setAttribute('aria-hidden','true');}
function populateMissionAgents(){$('#missionAgent').innerHTML=FLEET_IDS.map(id=>`<option value="${id}">${esc(CFG_NAME[id])} — ${esc(CFG[id].role)}</option>`).join('');}
function openMissionFor(id){populateMissionAgents();$('#missionAgent').value=id;openModal('missionModal');}
window.openMissionFor=openMissionFor;
const VIEWS=['overview','agents','missions','automations','analytics','systems'];
function viewFromPath(){const seg=location.pathname.replace(/^\/+|\/+$/g,'').split('/')[0]||'overview';return VIEWS.includes(seg)?seg:'overview';}
function switchView(name,push){
 if(!VIEWS.includes(name))name='overview';
 if(push===undefined)push=true;
 VIEW=name;
 $$('.view').forEach(v=>v.classList.remove('active'));const el=$('#'+name+'View');if(el)el.classList.add('active');
 $$('.line-sidebar__item').forEach(n=>{const on=n.dataset.view===name;n.classList.toggle('active',on);if(on)n.setAttribute('aria-current','true');else n.removeAttribute('aria-current');});
 const titles={overview:'Agent Headquarters',agents:'Agent Directory',missions:'Mission Control',automations:'Automations & Schedule',analytics:'Website Analytics',systems:'Systems Overview'};
 $('#viewTitle').textContent=titles[name]||name;$('#breadcrumb').textContent=(name==='overview'?'OVERVIEW':name.toUpperCase());
 if(DATA)renderView(name);
 placeNavActive();
 if(push){const path=name==='overview'?'/':'/'+name;if(location.pathname!==path)history.pushState({view:name},'',path);}
 window.scrollTo({top:0,behavior:'smooth'});
}
/* Line-Sidebar (React Bits – Proximity-Effekt) + Border-Glow (cursorfolgender Rahmen).
   Ein einziger rAF-Loop east je Item --effect (0..1) framerate-unabhängig auf sein
   Ziel zu; Farbe, Verschiebung und Marker-Skalierung lesen denselben Wert und
   laufen synchron – keine gestaffelten CSS-Transitions. */
function setupChrome(){
 const list=$('#navList');
 if(list){
  const items=$$('.line-sidebar__item',list);
  const targets=items.map(()=>0),current=items.map(()=>0);
  let raf=null,last=0;
  const smoothing=120,radius=130,ease=p=>p*p*(3-2*p);   // "smooth"-Falloff
  const actIdx=()=>items.findIndex(el=>el.classList.contains('active'));
  function frame(now){
   const dt=Math.min((now-last)/1000,.05);last=now;
   const tau=Math.max(smoothing,1)/1000,k=1-Math.exp(-dt/tau),act=actIdx();
   let moving=false;
   for(let i=0;i<items.length;i++){
    const target=Math.max(targets[i]||0,act===i?1:0),cur=current[i]||0,next=cur+(target-cur)*k;
    const settled=Math.abs(target-next)<.0015,val=settled?target:next;
    current[i]=val;items[i].style.setProperty('--effect',val.toFixed(4));
    if(!settled)moving=true;
   }
   raf=moving?requestAnimationFrame(frame):null;
  }
  function start(){if(raf!=null)return;last=(typeof performance!=='undefined'?performance.now():0);raf=requestAnimationFrame(frame);}
  list.addEventListener('pointermove',e=>{
   const r=list.getBoundingClientRect(),py=e.clientY-r.top;
   for(let i=0;i<items.length;i++){const c=items[i].offsetTop+items[i].offsetHeight/2;
    targets[i]=ease(Math.max(0,1-Math.abs(py-c)/radius));}
   start();
  });
  list.addEventListener('pointerleave',()=>{for(let i=0;i<targets.length;i++)targets[i]=0;start();});
  placeNavActive=start;     // switchView stößt den Loop bei Aktivwechsel an
  start();
 }
 const GLOW='.panel,.metric-card,.agent-card,.system-tile,.sum-card,.health-card,.task-card';
 document.addEventListener('pointermove',e=>{const el=e.target.closest&&e.target.closest(GLOW);if(!el)return;
  const r=el.getBoundingClientRect();el.style.setProperty('--gx',(e.clientX-r.left)+'px');el.style.setProperty('--gy',(e.clientY-r.top)+'px');},{passive:true});
 // Zeitspannen-Filter als Button + Popup-Card (Presets + freie Datum-/Stundenwahl)
 const pop=document.createElement('div');pop.className='rangepop';pop.hidden=true;
 pop.innerHTML=`<div class="rp-title">Time range</div>
  <div class="rp-presets"><button data-preset="24h">24 hours</button><button data-preset="7d">7 days</button><button data-preset="30d">30 days</button></div>
  <div class="rp-sep">or pick a custom window</div>
  <div class="rp-custom"><label>From<input type="datetime-local" id="rpFrom"></label><label>To<input type="datetime-local" id="rpTo"></label></div>
  <button class="rp-apply" id="rpApply">Apply custom range</button>`;
 document.body.appendChild(pop);
 const openPop=btn=>{
  pop.querySelectorAll('.rp-presets button').forEach(b=>b.classList.toggle('active',RANGE!=='custom'&&b.dataset.preset===RANGE));
  const now=Date.now();
  pop.querySelector('#rpFrom').value=toLocalInput(RANGE==='custom'?RFROM:now-rangeWinMs());
  pop.querySelector('#rpTo').value=toLocalInput(RANGE==='custom'?RTO:now);
  pop.hidden=false;pop.dataset.open='1';
  const r=btn.getBoundingClientRect(),w=pop.offsetWidth||280;
  pop.style.left=Math.max(8,Math.min(r.left,innerWidth-w-8))+'px';pop.style.top=(r.bottom+6)+'px';
 };
 const closePop=()=>{pop.hidden=true;pop.dataset.open='';pop.__anchor=null;};
 pop.querySelectorAll('.rp-presets button').forEach(b=>b.addEventListener('click',()=>{setRange(b.dataset.preset);closePop();}));
 pop.querySelector('#rpApply').addEventListener('click',()=>{
  const f=new Date(pop.querySelector('#rpFrom').value).getTime(),t=new Date(pop.querySelector('#rpTo').value).getTime();
  if(isNaN(f)||isNaN(t)||t<=f){toast('Invalid range','Pick a valid From/To (To must be after From).','err');return;}
  setCustomRange(f,t);closePop();
 });
 document.addEventListener('click',e=>{
  const btn=e.target.closest&&e.target.closest('[data-rangebtn]');
  if(btn){e.stopPropagation();if(pop.dataset.open&&pop.__anchor===btn)closePop();else{pop.__anchor=btn;openPop(btn);}return;}
  if(pop.dataset.open&&!(e.target.closest&&e.target.closest('.rangepop')))closePop();
 });
 // Hover-Tooltips (data-tip) als kleines Popup
 const tipEl=document.createElement('div');tipEl.className='hovertip';document.body.appendChild(tipEl);
 document.addEventListener('pointermove',e=>{
  const t=e.target.closest&&e.target.closest('[data-tip]');
  if(!t){if(tipEl.classList.contains('on'))tipEl.classList.remove('on');return;}
  tipEl.textContent=t.getAttribute('data-tip');tipEl.classList.add('on');
  const pad=14,w=tipEl.offsetWidth,h=tipEl.offsetHeight;
  let x=e.clientX+pad,y=e.clientY+pad;
  if(x+w>innerWidth-8)x=e.clientX-w-pad;if(y+h>innerHeight-8)y=e.clientY-h-pad;
  tipEl.style.left=Math.max(6,x)+'px';tipEl.style.top=Math.max(6,y)+'px';
 },{passive:true});
}

function bindEvents(){
 $$('.line-sidebar__item').forEach(n=>n.addEventListener('click',()=>switchView(n.dataset.view)));
 $$('[data-goview]').forEach(b=>b.addEventListener('click',()=>switchView(b.dataset.goview)));
 $('#seeMissionsBtn').addEventListener('click',()=>switchView('missions'));
 $('#refreshBtn').addEventListener('click',()=>load());
 $('#fitMapBtn').addEventListener('click',()=>{if(typeof camFit==='function')camFit();});
 $('#newMissionBtn').addEventListener('click',()=>{populateMissionAgents();openModal('missionModal');});
 $('#openCommandBtn').addEventListener('click',()=>openModal('commandModal'));
 $$('[data-close]').forEach(b=>b.addEventListener('click',()=>closeModal(b.dataset.close)));
 $$('.modal-backdrop').forEach(m=>m.addEventListener('click',e=>{if(e.target===m)closeModal(m.id);}));
 $('#drawerClose').addEventListener('click',closeDrawer);
 $$('.suggestion-grid button').forEach(b=>b.addEventListener('click',()=>{$('#commandInput').value=b.dataset.command;}));
 $('#executeCommandBtn').addEventListener('click',()=>sendToCommander($('#commandInput').value,()=>closeModal('commandModal')));
 $('#commandSendBtn').addEventListener('click',()=>sendToCommander($('#commandTextarea').value,()=>{$('#commandTextarea').value='';},$('#commandMsg')));
 $('#searchBtn').addEventListener('click',()=>{switchView('agents');setTimeout(()=>$('#agentSearch').focus(),120);});
 $('#agentSearch').addEventListener('input',()=>renderAgents());
 $('#agentFilters').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{AGENT_FILTER=b.dataset.filter;$('#agentFilters').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));renderAgents();}));
 $('#focusCriticalBtn').addEventListener('click',()=>goAgents('alert'));
 const bell=$('.notification');if(bell)bell.addEventListener('click',()=>goAgents('alert'));
 $('#scheduleSaveBtn').addEventListener('click',saveSchedule);
 $('#missionForm').addEventListener('submit',e=>{e.preventDefault();const id=$('#missionAgent').value,txt=$('#missionDescription').value.trim();
  closeModal('missionModal');startRun(id,null,txt?('Nutze den Subagent '+id+'. Sebastians Auftrag für diesen Lauf: '+txt):null);e.target.reset();});
 document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openModal('commandModal');setTimeout(()=>$('#commandInput').focus(),50);}
  if(e.key==='Escape'){$$('.modal-backdrop.open').forEach(m=>closeModal(m.id));closeDrawer();}
 });
}
function sendToCommander(txt,done,msgEl){
 txt=(txt||'').trim();if(!txt){if(msgEl)flash(msgEl,'Please type an order first.',false);else toast('Order missing','Describe the task first.','err');return;}
 if(done)done();
 startRun('master',null,'Nutze den Subagent kommandant. Sebastians Auftrag für diesen Lauf: '+txt+' — koordiniere entsprechend, halte dich an deine Regeln, sende nichts nach außen ohne Go.');
 if($('#commandInput'))$('#commandInput').value='';
 if(msgEl)flash(msgEl,'Handed to the commander ✓',true);
}

/* ================================================================
   BOOT
   ================================================================ */
initBots();
/* Default view: fit the whole station (no zoom). */
function defaultView(){if(typeof WORLD_W==='undefined'||!WORLD_W)return;
 camT.scale=camMin;camT.x=WORLD_W/2;camT.y=WORLD_H/2;
 clampObj(camT);cam.scale=camT.scale;cam.x=camT.x;cam.y=camT.y;clampCam();}
requestAnimationFrame(()=>requestAnimationFrame(defaultView));
requestAnimationFrame(t=>{lastT=t;requestAnimationFrame(loop);});
bindEvents();
setupChrome();
switchView(viewFromPath(),false);                    // initiale Ansicht aus der URL
window.addEventListener('popstate',()=>switchView(viewFromPath(),false));
detectApi().then(load);
