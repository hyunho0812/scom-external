#!/usr/bin/env python3
"""Build the self-contained Korean dashboard (index.html).
Filters: region(7) → country(12) → division(MX/VD/DA) → KPI → impact → date range.
Trend graph: Samsung baseline + selected-division competitor total (Wikipedia views),
with numbered callout markers for events mapped to a list below.
Cards: one-line impact summary + plain-language body + affected KPIs."""
import os, json
from datetime import datetime, timezone

HERE=os.path.dirname(__file__)
DATA=os.path.join(HERE,"..","data","events.json")
WIKI=os.path.join(HERE,"..","data","wiki_views.json")
MSTAT=os.path.join(HERE,"..","data","model_status.json")
OUT=os.path.join(HERE,"..","index.html")

events=json.load(open(DATA,encoding="utf-8"))
updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
try: wiki=json.load(open(WIKI,encoding="utf-8"))
except Exception: wiki={"series":{},"divisions":{}}
try: mstat=json.load(open(MSTAT,encoding="utf-8"))
except Exception: mstat={"model":"unknown","status":"unknown","last_checked":"n/a","note":""}

HTML=r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>S.com External Factors</title>
<style>
:root{--blue:#1428A0;--ink:#1a1a1a;--muted:#6b6b6b;--line:#e6e6e6;--bg:#f7f8fa;--card:#fff;--neg:#E24B4A;--pos:#1D9E75;--neu:#9a9a96}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Malgun Gothic',Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5;padding:24px;max-width:1100px;margin:0 auto}
h1{font-size:20px;font-weight:500;color:var(--blue);margin-bottom:4px}
.sub{font-size:13px;color:var(--muted);margin-bottom:14px}
.mbadge{display:inline-flex;align-items:center;gap:7px;font-size:12px;padding:5px 11px;border-radius:20px;margin-bottom:18px;border:1px solid var(--line)}
.mbadge .dot{width:8px;height:8px;border-radius:50%}
.mbadge.ok{background:#e9f7ef;border-color:#bfe6cd;color:#1d6b3f}.mbadge.ok .dot{background:#1D9E75}
.mbadge.retired{background:#fdecea;border-color:#f5c2bd;color:#a3271f}.mbadge.retired .dot{background:#E24B4A}
.mbadge.unknown,.mbadge.error{background:#fef7e0;border-color:#f0e2b8;color:#8a6d1a}
.mbadge.unknown .dot,.mbadge.error .dot{background:#EF9F27}
.controls{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.ctrl{display:flex;flex-direction:column;gap:5px}.ctrl label{font-size:11px;color:var(--muted)}
select,input[type=date]{padding:8px 12px;border:1px solid var(--line);border-radius:8px;font-size:14px;background:#fff;cursor:pointer}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:18px}
.phead{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:6px}
.ptitle{font-size:13px;font-weight:500}
.legend{display:flex;gap:14px;font-size:11px;color:var(--muted);flex-wrap:wrap}
.note{font-size:11px;color:var(--color-text-tertiary,#999);margin-top:8px}
.evmap{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1rem}
.card .lbl{font-size:12px;color:var(--muted);margin-bottom:6px}.card .val{font-size:24px;font-weight:500}
.funnel{font-size:11px;color:var(--muted);margin-bottom:16px}
.evt{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--neu);border-radius:10px;padding:14px 16px;margin-bottom:12px}
.evt.pos{border-left-color:var(--pos)}.evt.neg{border-left-color:var(--neg)}
.evt .top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:5px}
.evt .ttl{font-size:15px;font-weight:500}.evt .meta{font-size:12px;color:var(--muted)}
.evt .imp{font-size:13px;font-weight:500;border-radius:8px;padding:8px 10px;margin:6px 0 8px;line-height:1.5}
.evt .desc{font-size:13px;color:#444;line-height:1.65}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;background:#eef0f5;color:#444;margin-right:5px}
.kline{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px}.klbl{font-size:11px;color:var(--muted)}
.ktag{display:inline-block;font-size:11px;padding:2px 9px;border-radius:10px;margin-right:5px;font-weight:500}
.empty{padding:30px;text-align:center;color:var(--muted)}
.foot{font-size:12px;color:#8a6d1a;margin-top:16px;padding:12px;background:#fff8e8;border:1px solid #f0e2b8;border-radius:10px}
</style></head><body>
<h1>S.com External Factors</h1>
<div class="sub">매일 자동 갱신 · 마지막 빌드 __UPDATED__</div>
<div class="mbadge __MSTATUS__" title="__MNOTE__"><span class="dot"></span>
  <span>필터 모델: <strong>__MMODEL__</strong> — __MLABEL__ · 점검 __MCHECKED__</span></div>
<div class="controls">
 <div class="ctrl"><label>지역</label><select id="region"></select></div>
 <div class="ctrl"><label>국가</label><select id="country"></select></div>
 <div class="ctrl"><label>사업부</label><select id="div">
   <option value="ALL">전체</option><option value="MX">MX</option><option value="VD">VD</option><option value="DA">DA</option></select></div>
 <div class="ctrl"><label>KPI</label><select id="kpi">
   <option value="ALL">전체</option><option>Impression</option><option>Click</option><option>Traffic</option><option>Order</option><option>CVR</option><option>Revenue</option><option>AOV</option></select></div>
 <div class="ctrl"><label>영향</label><select id="dir">
   <option value="ALL">전체</option><option value="-">부정</option><option value="+">긍정</option><option value="neutral">중립</option></select></div>
 <div class="ctrl"><label>시작일</label><input type="date" id="sd"></div>
 <div class="ctrl"><label>종료일</label><input type="date" id="ed"></div>
 <button id="csvbtn" style="margin-left:auto;padding:9px 16px;border:none;border-radius:8px;background:var(--blue);color:#fff;font-size:13px;font-weight:500;cursor:pointer">CSV 내보내기</button>
</div>

<div class="panel">
  <div class="phead"><div class="ptitle">위키피디아 조회수 추세 <span id="tsub" style="font-size:11px;color:#999;font-weight:400"></span></div>
    <div class="legend" id="legend"></div></div>
  <div style="position:relative;height:250px"><canvas id="trend"></canvas></div>
  <div class="note">번호 말풍선 = 외부 요인 발생 시점(아래 목록과 연결) · 위키피디아 일별 조회수(외부 추정 신호, 경쟁사 실측 트래픽 아님)</div>
  <div class="evmap" id="evmap"></div>
</div>

<div class="cards" id="cards"></div>
<div class="funnel">KPI 퍼널: 노출(Impression) → 클릭(Click) → 트래픽(Traffic) → 주문(Order) · 전환율(CVR) → 매출(Revenue) · 객단가(AOV)</div>
<div id="list"></div>
<div class="foot">이벤트는 samsung.com 관련성 기준으로 자동 수집·필터링됩니다. 자동 필터는 완벽하지 않으니 주기적으로 검수하세요. 영향 방향·KPI·조회수는 추정/대리 신호이며 측정된 인과나 실측 트래픽이 아닙니다. 사업부: MX=Apple, VD=LG, DA=Whirlpool. Samsung은 항상 기준선.</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/chartjs-plugin-annotation/3.0.1/chartjs-plugin-annotation.min.js"></script>
<script>
const EV=__DATA__;
const WIKI=__WIKI__;
const REGIONS={"ALL":null,"북미":["US"],"유럽":["GB","DE","FR","ES","PT"],"중남미":["BR","MX_C"],"동남아":["AU"],"서남아":["IN"],"중동":["TR"],"한국":["KR"]};
const COUNTRIES=[["ALL","전체"],["US","미국"],["GB","영국"],["DE","독일"],["FR","프랑스"],["ES","스페인"],["PT","포르투갈"],["BR","브라질"],["MX_C","멕시코"],["AU","호주"],["IN","인도"],["TR","튀르키예"],["KR","한국"]];
const DIV2COMP={MX:"Apple",VD:"LG",DA:"Whirlpool"};
const DIRLAB={"-":"부정","+":"긍정","neutral":"중립","unknown":"미상"};
const DIRC={"-":"#E24B4A","+":"#1D9E75","neutral":"#9a9a96","unknown":"#9a9a96"};
const DIRCLS={"-":"neg","+":"pos","neutral":"","unknown":""};
const KPIORDER=["Impression","Click","Traffic","Order","CVR","Revenue","AOV"];
const KPICOL={Impression:"#185FA5",Click:"#185FA5",Traffic:"#185FA5",Order:"#534AB7",CVR:"#534AB7",Revenue:"#534AB7",AOV:"#534AB7"};
const KPIBG={Impression:"#E6F1FB",Click:"#E6F1FB",Traffic:"#E6F1FB",Order:"#EEEDFE",CVR:"#EEEDFE",Revenue:"#EEEDFE",AOV:"#EEEDFE"};
const region=document.getElementById('region'),country=document.getElementById('country'),dv=document.getElementById('div'),kpi=document.getElementById('kpi'),d=document.getElementById('dir'),sd=document.getElementById('sd'),ed=document.getElementById('ed');
region.innerHTML=Object.keys(REGIONS).map((r,i)=>`<option value="${r}"${i===0?' selected':''}>${r==='ALL'?'전체':r}</option>`).join('');
function syncCountries(){const reg=REGIONS[region.value];
 const list=reg?COUNTRIES.filter(c=>c[0]==='ALL'||reg.includes(c[0])):COUNTRIES;
 country.innerHTML=list.map((c,i)=>`<option value="${c[0]}"${i===0?' selected':''}>${c[1]}</option>`).join('');}
syncCountries();
function activeCountrySet(){if(country.value!=='ALL')return [country.value];const reg=REGIONS[region.value];return reg?reg:null;}
function rows(){let r=EV.slice();const cs=activeCountrySet();
 if(cs)r=r.filter(e=>(e.scope||'').split(';').some(s=>cs.includes(s)));
 if(dv.value!=='ALL')r=r.filter(e=>(e.divisions||'').split(';').includes(dv.value));
 if(kpi.value!=='ALL')r=r.filter(e=>(e.kpi||'').split(';').includes(kpi.value));
 if(d.value!=='ALL')r=r.filter(e=>e.impact_direction===d.value);
 if(sd.value)r=r.filter(e=>(e.date||'')>=sd.value);
 if(ed.value)r=r.filter(e=>(e.date||'')<=ed.value);
 return r.sort((a,b)=>(b.date||'').localeCompare(a.date||''));}

// ---- trend graph ----
function wikiSeries(brand){return (WIKI.series&&WIKI.series[brand])||[];}
function compNames(){return dv.value==='ALL'?["Apple","LG","Whirlpool"]:[DIV2COMP[dv.value]];}
function compLabel(){return dv.value==='ALL'?'경쟁사 합산':compNames()[0];}
let chart;
function drawTrend(evSortedAsc){
 const sam=wikiSeries("Samsung");
 const labels=sam.map(p=>p.date);
 const samData=sam.map(p=>p.views);
 const names=compNames();
 const total=labels.map((dt,i)=>names.reduce((s,n)=>{const ser=wikiSeries(n);const f=ser.find(p=>p.date===dt);return s+(f?f.views:0);},0));
 const ann={};
 evSortedAsc.forEach((e,i)=>{
  let near=labels[0]; for(const dt of labels){ if(dt<=e.date) near=dt; }
  ann['e'+i]={type:'label',xValue:near,yValue:Math.max(...samData,...total),
   content:[String(i+1)],backgroundColor:DIRC[e.impact_direction]||'#999',color:'#fff',
   font:{size:12,weight:'bold'},padding:{top:3,bottom:3,left:8,right:8},borderRadius:10,yAdjust:-4,
   callout:{display:true,borderColor:DIRC[e.impact_direction]||'#999',borderWidth:1,margin:4}};
 });
 document.getElementById('legend').innerHTML=
  `<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;background:#1428A0;display:inline-block"></span>Samsung (기준)</span>`+
  `<span style="display:flex;align-items:center;gap:5px"><span style="width:12px;height:2px;background:#888;display:inline-block"></span>${compLabel()}</span>`;
 document.getElementById('tsub').textContent='(일별 조회수, 합산)';
 if(chart)chart.destroy();
 chart=new Chart(document.getElementById('trend'),{type:'line',
  data:{labels,datasets:[
   {label:'Samsung',data:samData,borderColor:'#1428A0',backgroundColor:'#1428A014',tension:0.3,pointRadius:0,borderWidth:2.5},
   {label:compLabel(),data:total,borderColor:'#888780',backgroundColor:'#88878014',tension:0.3,pointRadius:0,borderWidth:2}]},
  options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:18}},
   plugins:{legend:{display:false},annotation:{annotations:ann},
     tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.parsed.y||0).toLocaleString()+'회'}}},
   scales:{x:{ticks:{color:'#888780',font:{size:11},maxTicksLimit:8},grid:{display:false}},
     y:{ticks:{color:'#888780',font:{size:11},callback:v=>(v/1000)+'k'},grid:{color:'rgba(136,135,128,0.12)'}}}}});
}

function kpiTags(k){const list=(k||'').split(';').filter(x=>x).sort((a,b)=>KPIORDER.indexOf(a)-KPIORDER.indexOf(b));
 return list.map(x=>`<span class="ktag" style="background:${KPIBG[x]||'#eee'};color:${KPICOL[x]||'#444'}">${x}</span>`).join('');}

function render(){const r=rows();
 const evAsc=r.slice().sort((a,b)=>(a.date||'').localeCompare(b.date||''));
 drawTrend(evAsc);
 document.getElementById('evmap').innerHTML = evAsc.length? evAsc.map((e,i)=>`
   <div style="display:flex;gap:10px;align-items:flex-start;margin-bottom:8px">
     <span style="flex:none;width:20px;height:20px;border-radius:50%;background:${DIRC[e.impact_direction]||'#999'};color:#fff;font-size:11px;font-weight:bold;display:flex;align-items:center;justify-content:center;margin-top:1px">${i+1}</span>
     <div style="flex:1"><div style="font-size:13px;font-weight:500">${e.title} <span style="font-size:11px;color:#999;font-weight:400">· ${e.date||''} · ${DIRLAB[e.impact_direction]||''}</span></div>
       <div style="font-size:12px;color:var(--muted);margin-top:1px">${e.impact||''}</div></div>
   </div>`).join('') : '<div style="font-size:12px;color:#999">해당 조건의 요인이 없습니다.</div>';

 const neg=r.filter(x=>x.impact_direction==='-').length;
 const scopeLabel=country.value!=='ALL'?(COUNTRIES.find(c=>c[0]===country.value)||['','전체'])[1]:(region.value!=='ALL'?region.value:'전체');
 document.getElementById('cards').innerHTML=
  `<div class="card"><div class="lbl">표시된 이벤트</div><div class="val">${r.length}</div></div>`+
  `<div class="card"><div class="lbl">부정 영향</div><div class="val" style="color:var(--neg)">${neg}</div></div>`+
  `<div class="card"><div class="lbl">대상</div><div class="val" style="font-size:18px">${scopeLabel}</div></div>`;
 document.getElementById('list').innerHTML = r.length? r.map(e=>{
   const cls=DIRCLS[e.impact_direction]||'';const bc=DIRC[e.impact_direction]||'#9a9a96';
   const divs=(e.divisions||'').split(';').filter(x=>x);
   const meta=[...divs,DIRLAB[e.impact_direction]||'',e.confidence||''].filter(x=>x);
   const imp=e.impact?`<div class="imp" style="color:${bc};background:${bc}14">${e.impact}</div>`:'';
   return `<div class="evt ${cls}"><div class="top"><span class="ttl">${e.title}</span><span class="meta">${e.date||''}</span></div>
     <div>${meta.map(t=>`<span class="tag">${t}</span>`).join('')}</div>${imp}
     <div class="desc">${e.description||''}</div>
     <div class="kline"><span class="klbl">영향 KPI:</span>${kpiTags(e.kpi)}</div></div>`;}).join('') : '<div class="empty">해당 조건에 맞는 이벤트가 없습니다.</div>';}
function exportCSV(){const r=rows();
 const h=['date','scope','divisions','kpi','title','impact','description','impact_direction','confidence','source'];
 const csv=[h.join(',')].concat(r.map(x=>h.map(k=>`"${(x[k]||'').toString().replace(/"/g,'""')}"`).join(','))).join('\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='scom_external_factors.csv';a.click();}
document.getElementById('csvbtn').onclick=exportCSV;
region.onchange=()=>{syncCountries();render();};
[country,dv,kpi,d,sd,ed].forEach(el=>el.onchange=render);render();
</script></body></html>"""

LABELS={"ok":"정상 ✓","retired":"종료됨 — GEMINI_MODEL 교체 필요","unknown":"키 없음 (키워드 필터만)","error":"점검 실패 — 확인 필요"}
HTML=(HTML.replace("__DATA__",json.dumps(events,ensure_ascii=False))
          .replace("__WIKI__",json.dumps(wiki,ensure_ascii=False))
          .replace("__MSTATUS__",mstat.get("status","unknown"))
          .replace("__MMODEL__",str(mstat.get("model","unknown")))
          .replace("__MLABEL__",LABELS.get(mstat.get("status","unknown"),"상태 미상"))
          .replace("__MCHECKED__",str(mstat.get("last_checked","n/a")))
          .replace("__MNOTE__",str(mstat.get("note","")).replace('"',"'"))
          .replace("__UPDATED__",updated))
open(OUT,"w",encoding="utf-8").write(HTML)
print("built index.html with",len(events),"events, wiki series:",list(wiki.get("series",{}).keys()))
