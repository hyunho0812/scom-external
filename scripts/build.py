#!/usr/bin/env python3
"""Build the self-contained Korean dashboard (index.html).
Filters: region(7) → country(12) → division(MX/VD/DA) → KPI → impact → date range.
Trend graph: Samsung baseline + selected-division company total (Wikipedia views),
with numbered callout markers for events mapped to a list below.
Cards: one-line impact summary + plain-language body + affected KPIs."""
import os, sys, json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Shared with the collectors so the page and the pipeline cannot disagree
# about where files live or which countries a region holds.
from llm_common import (SCOPE_REGIONS, EVENTS_FILE, WIKI_FILE, CRUX_FILE,
                        MODEL_STATUS_FILE, PREDICTION_SCORES_FILE,
                        LLM_AGREEMENT_FILE, FEED_HEALTH_FILE, INDEX_HTML, read_json)

events=read_json(EVENTS_FILE, [])
updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Default period: year-to-date YoY (current = Jan 1..today, comparison = last year Jan 1..same day)
_today = datetime.now(timezone.utc).date()
DEF_CUR_FROM = _today.replace(month=1, day=1).isoformat()
DEF_CUR_TO   = _today.isoformat()
try:
    _ly_to = _today.replace(year=_today.year-1)
except ValueError:
    _ly_to = _today.replace(year=_today.year-1, day=28)  # 2/29 보정
DEF_CMP_FROM = _ly_to.replace(month=1, day=1).isoformat()
DEF_CMP_TO   = _ly_to.isoformat()
# Every input is optional except events.json: on a fresh clone the collectors
# and the credibility layer have not run yet, and the page degrades to
# "측정 없음" for the missing panels rather than failing to build.
wiki=read_json(WIKI_FILE, {"series":{},"divisions":{}})
mstat=read_json(MODEL_STATUS_FILE, {})
_MSTAT_DEFAULT={"model":"unknown","status":"unknown","note":""}
def _mstat_of(name):
    return mstat.get(name, _MSTAT_DEFAULT) or _MSTAT_DEFAULT
crux=read_json(CRUX_FILE, {"metrics":{}})
scores=read_json(PREDICTION_SCORES_FILE, {})
_ag=read_json(LLM_AGREEMENT_FILE, {})
agreement=(_ag[-1] if isinstance(_ag,list) and _ag else (_ag if isinstance(_ag,dict) else {}))

HTML=r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>External Event Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{
  --bg:oklch(0.19 0.006 250);      /* page */
  --card:oklch(0.205 0.006 250);   /* panel surface */
  --chrome:oklch(0.163 0.006 250); /* top bar + tabs */
  --strip:oklch(0.222 0.006 250);  /* header strips inside cards */
  --row:oklch(0.198 0.006 250);    /* list rows */
  --row-on:oklch(0.228 0.008 250); /* selected row */
  --line:oklch(0.27 0.008 250);
  --line-2:oklch(0.245 0.008 250);
  --ink:oklch(0.93 0.004 250);
  --ink-2:oklch(0.86 0.004 250);
  --muted:oklch(0.60 0.008 250);
  --muted-2:oklch(0.50 0.008 250);
  --accent:oklch(0.78 0.11 195);
  --pos:oklch(0.72 0.15 155);
  --neg:oklch(0.70 0.16 25);
  --warn:oklch(0.78 0.13 85);
  --neu:oklch(0.62 0.008 250);
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --pad:28px;      /* page gutter */
  --gap:20px;      /* vertical rhythm */
  --side:420px;    /* right column */
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'IBM Plex Sans KR',system-ui,-apple-system,'Malgun Gothic',sans-serif;
  background:var(--card);color:var(--ink);line-height:1.55;font-size:13px}
a{color:var(--accent);text-decoration:none}a:hover{color:oklch(0.86 0.11 195)}
.mono{font-family:var(--mono)}

/* ---- chrome ---- */
.topbar{display:flex;align-items:center;justify-content:space-between;gap:24px;
  padding:13px var(--pad);background:var(--chrome)}
.topbar .brand{display:flex;align-items:baseline;gap:13px}
.topbar h1{font-size:14px;font-weight:600;letter-spacing:-0.01em}
.topbar .sub{font-family:var(--mono);font-size:11px;color:var(--muted);font-weight:400}
.mbadges{display:flex;align-items:center;gap:16px;font-family:var(--mono);font-size:10.5px;color:oklch(0.64 0.008 250)}
.mbadge{display:inline-flex;align-items:center;gap:5px}
.mbadge .dot{width:5px;height:5px;border-radius:50%;background:var(--neu)}
.mbadge.ok .dot{background:var(--pos)}
.mbadge.retired .dot{background:var(--neg)}
.mbadge.unknown .dot,.mbadge.error .dot{background:var(--warn)}
.tabbar{display:flex;padding:0 var(--pad);background:var(--chrome);border-bottom:1px solid var(--line)}
.tab{font-family:inherit;font-size:12.5px;font-weight:400;color:var(--muted);background:none;border:none;
  border-bottom:2px solid transparent;margin-bottom:-1px;padding:9px 14px;cursor:pointer}
.tab.active{color:oklch(0.95 0.004 250);font-weight:600;border-bottom-color:var(--accent)}
.tabpane{display:none}.tabpane.active{display:block}

/* ---- filter strip ---- */
.controls{display:flex;align-items:center;gap:7px;flex-wrap:wrap;
  padding:11px var(--pad);background:oklch(0.176 0.006 250);border-bottom:1px solid var(--line-2)}
.ctrl{display:flex;align-items:center;gap:7px;height:28px;padding:0 4px 0 10px;
  border:1px solid oklch(0.30 0.008 250);border-radius:3px;background:oklch(0.215 0.006 250)}
.ctrl label{font-family:var(--mono);font-size:9.5px;letter-spacing:.07em;color:oklch(0.57 0.008 250);white-space:nowrap}
select,input[type=date]{font-family:inherit;font-size:12px;font-weight:500;color:var(--ink);
  background:transparent;border:none;height:26px;padding:0 4px;cursor:pointer;max-width:150px}
select:focus,input[type=date]:focus{outline:1px solid var(--accent);border-radius:2px}
select option{background:oklch(0.215 0.006 250);color:var(--ink)}
input[type=date]{color-scheme:dark}
.btn,#csvbtn{font-family:var(--mono);font-size:10px;letter-spacing:.07em;height:28px;padding:0 12px;
  border:1px solid oklch(0.31 0.008 250);border-radius:3px;background:transparent;color:oklch(0.76 0.004 250);cursor:pointer}
.btn:hover,#csvbtn:hover{border-color:var(--accent);color:var(--accent)}
.spacer{flex-grow:1}
.rowbreak{flex-basis:100%;height:0}
.controls .foot:not(:empty){margin-top:8px;margin-right:14px}

/* ---- layout ---- */
.wrap{padding:var(--gap) var(--pad) 40px;display:flex;flex-direction:column;gap:var(--gap)}
.split{display:grid;grid-template-columns:minmax(0,1fr) var(--side);gap:var(--gap);align-items:start}
@media (max-width:1180px){.split{grid-template-columns:minmax(0,1fr)}}

/* ---- panels & cards ---- */
.panel{background:var(--card);border:1px solid var(--line);border-radius:3px;padding:15px 18px 16px}
.phead{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:12px;margin-bottom:12px}
.ptitle{font-size:12.5px;font-weight:600;display:flex;align-items:baseline;gap:9px;min-width:0}
.ptitle>:first-child,.ptitle{white-space:nowrap}
.ptitle .psub{font-family:var(--mono);font-size:10px;color:oklch(0.55 0.008 250);font-weight:400;
  white-space:normal;min-width:0;overflow:hidden;text-overflow:ellipsis}
.legend{display:flex;gap:11px;font-family:var(--mono);font-size:9.5px;color:oklch(0.62 0.008 250)}
.note{font-size:10.5px;color:oklch(0.53 0.008 250);margin-top:10px;line-height:1.55}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:3px;overflow:hidden}
@media (max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
.card{background:var(--card);padding:14px 18px}
.card .lbl{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:oklch(0.57 0.008 250);margin-bottom:7px}
.card .val{font-family:var(--mono);font-size:24px;font-weight:500;letter-spacing:-0.02em}
.card .vnote{font-family:var(--mono);font-size:10px;color:oklch(0.58 0.008 250);margin-left:8px}

/* ---- event list (master) ---- */
.evlist{border:1px solid var(--line);border-radius:3px;overflow:hidden;display:flex;flex-direction:column;gap:1px;background:var(--line)}
.evstrip{background:var(--strip);padding:9px 14px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.fgroup{display:flex;align-items:center;gap:7px}
.fgroup>span.flbl{font-family:var(--mono);font-size:9px;letter-spacing:.09em;color:oklch(0.54 0.008 250)}
.seg{display:flex;border:1px solid oklch(0.30 0.008 250);border-radius:3px;overflow:hidden}
.seg button{font-family:var(--mono);font-size:10px;height:22px;padding:0 9px;background:transparent;
  color:oklch(0.62 0.008 250);border:none;border-left:1px solid oklch(0.30 0.008 250);cursor:pointer}
.seg button:first-child{border-left:none}
.seg button.on{background:oklch(0.30 0.03 195);color:oklch(0.94 0.02 195)}
.evt{background:var(--row);border-left:2px solid transparent;padding:12px 16px;
  display:grid;grid-template-columns:26px 16px minmax(0,1fr) 112px;gap:13px;align-items:start;cursor:pointer}
.evt:hover{background:oklch(0.215 0.006 250)}
.evt.on{background:var(--row-on);border-left-color:var(--accent)}
.evt .num{font-family:var(--mono);font-size:10.5px;color:oklch(0.48 0.008 250);padding-top:2px}
.evt .dir{font-family:var(--mono);font-size:12px;padding-top:1px}
.evt .ttl{font-size:13px;font-weight:500;letter-spacing:-0.005em;color:oklch(0.90 0.004 250);margin-bottom:4px}
.evt.on .ttl{font-weight:600;color:oklch(0.96 0.004 250)}
.evt .sum{font-size:12px;color:oklch(0.70 0.004 250);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.evt .rt{text-align:right}
.evt .date{font-family:var(--mono);font-size:10px;color:oklch(0.56 0.008 250)}
.evt .meta{font-family:var(--mono);font-size:9px;color:oklch(0.48 0.008 250);margin-top:3px}
.evt.pos .dir{color:var(--pos)}.evt.neg .dir{color:var(--neg)}
.empty{padding:28px;text-align:center;color:var(--muted);background:var(--row)}

/* ---- detail (slave) ---- */
.detail{background:var(--card);border:1px solid var(--line);border-radius:3px;padding:15px 18px 16px;
  display:flex;flex-direction:column;gap:13px;position:sticky;top:16px}
.dhead{display:flex;align-items:center;justify-content:space-between;padding-bottom:11px;border-bottom:1px solid var(--line-2)}
.dhead .k{font-family:var(--mono);font-size:9.5px;letter-spacing:.11em;color:var(--muted)}
.dhead .d{font-family:var(--mono);font-size:10px;color:oklch(0.56 0.008 250)}
.dttl{font-size:15px;font-weight:600;letter-spacing:-0.01em;line-height:1.45}
.tags{display:flex;flex-wrap:wrap;gap:4px}
.tag{font-family:var(--mono);font-size:9.5px;letter-spacing:.04em;padding:3px 8px;
  border:1px solid oklch(0.30 0.008 250);border-radius:3px;color:oklch(0.70 0.008 250)}
.blk{border-left:2px solid oklch(0.40 0.01 250);padding-left:12px}
.blk.inf{border-left-color:var(--warn)}
.blk .blbl{display:block;font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:oklch(0.57 0.008 250);margin-bottom:5px}
.blk.inf .blbl{color:var(--warn)}
.blk .txt{font-size:12.5px;color:var(--ink-2)}
.blk.inf .txt{color:oklch(0.76 0.05 85)}
.kline{display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid var(--line-2)}
.klbl{font-family:var(--mono);font-size:9.5px;letter-spacing:.06em;color:oklch(0.56 0.008 250)}
.metaval{font-size:11.5px;font-weight:500;text-align:right;color:oklch(0.88 0.004 250)}
.dacts{display:flex;gap:6px;margin-top:2px}
.dacts .btn{flex-grow:1;height:30px;text-align:center}

/* ---- axis panel ---- */
.tsum{display:flex;flex-direction:column;gap:7px;padding-bottom:14px;margin-bottom:14px;border-bottom:1px solid var(--line-2)}
.tsum .ln{display:grid;grid-template-columns:14px minmax(0,1fr);gap:9px;align-items:start}
.tsum .n{font-family:var(--mono);font-size:10px;color:oklch(0.50 0.008 250);padding-top:2px}
.tsum .t{font-size:12.5px;color:var(--ink-2);line-height:1.58}
.axrow{display:grid;grid-template-columns:72px minmax(0,1fr) 58px;gap:12px;align-items:center;margin-bottom:8px}
.axrow .an{font-size:12px;font-weight:600}
.axrow .ae{font-family:var(--mono);font-size:9px;color:oklch(0.52 0.008 250);letter-spacing:.05em}
.axbar{height:4px;border-radius:2px;background:oklch(0.26 0.008 250);overflow:hidden}
.axbar>i{display:block;height:4px;border-radius:2px}
.axval{font-family:var(--mono);font-size:15px;text-align:right}
.contrib{margin-top:14px;padding-top:13px;border-top:1px solid var(--line-2)}
.contrib .chead{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:10px}
.contrib .chead .k{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:oklch(0.57 0.008 250)}
.contrib .chead .v{font-family:var(--mono);font-size:9.5px;color:oklch(0.50 0.008 250)}
.cbar{display:flex;height:7px;border-radius:2px;overflow:hidden;gap:1px;margin-bottom:11px}
.crow{display:grid;grid-template-columns:9px minmax(0,1fr) 52px 52px;gap:9px;align-items:center;margin-bottom:6px}
.cdot{width:7px;height:7px;border-radius:2px}
.crow .cn{font-size:11.5px;color:oklch(0.90 0.004 250)}
.crow .cv{font-family:var(--mono);font-size:12.5px;text-align:right}
.crow .cx{font-family:var(--mono);font-size:10px;text-align:right;color:oklch(0.50 0.008 250)}

/* ---- glossary ---- */
.gintro{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:30px;align-items:start}
@media (max-width:900px){.gintro{grid-template-columns:minmax(0,1fr)}}
.ghead{display:flex;align-items:baseline;gap:10px;padding-bottom:9px;border-bottom:1px solid oklch(0.30 0.008 250);margin-bottom:14px}
.ggrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:3px;overflow:hidden}
@media (max-width:900px){.ggrid{grid-template-columns:minmax(0,1fr)}}
.gterm{background:var(--row);padding:15px 18px 16px}
.gterm .gt{display:flex;align-items:baseline;gap:9px;margin-bottom:8px}
.gterm .gko{font-size:13.5px;font-weight:600;letter-spacing:-0.005em}
.gterm .gen{font-family:var(--mono);font-size:10px;letter-spacing:.04em;color:oklch(0.52 0.008 250)}
.gterm .gdef{font-size:12.5px;color:var(--ink-2);margin-bottom:9px}
.gterm .grow{display:grid;grid-template-columns:62px minmax(0,1fr);gap:10px;row-gap:6px;align-items:start}
.gterm .gk{font-family:var(--mono);font-size:9.5px;letter-spacing:.05em;color:oklch(0.54 0.008 250);padding-top:2px}
.gterm .gv{font-size:12px;color:oklch(0.74 0.004 250)}
.gterm .gk.warn{color:oklch(0.62 0.10 25)}.gterm .gv.warn{color:oklch(0.74 0.05 25)}

.foot{font-size:11px;color:oklch(0.53 0.008 250);padding-top:6px}
.srcline{display:flex;gap:10px;flex-wrap:wrap;font-family:var(--mono);font-size:9.5px;color:oklch(0.48 0.008 250)}
.llmtag{font-style:normal}
.srclink{font-size:12px;word-break:break-all}
#trend{cursor:pointer}
.evt.flash{animation:flash 1.6s ease}
@keyframes flash{0%{background:var(--row-on)}25%{background:oklch(0.30 0.03 195)}100%{background:var(--row-on)}}
</style></head><body>

<div class="topbar">
  <div class="brand"><h1>External Event Ledger</h1><span class="sub">samsung.com</span></div>
  <div class="mbadges">__MBADGES__<span style="color:oklch(0.50 0.008 250)">__UPDATED__</span></div>
</div>

<div class="tabbar">
  <button class="tab active" data-tab="board">대시보드</button>
  <button class="tab" data-tab="glossary">용어 설명</button>
</div>

<div id="tab-board" class="tabpane active">

<div class="controls">
 <div class="ctrl"><label>지역</label><select id="region"></select></div>
 <div class="ctrl"><label>국가</label><select id="country"></select></div>
 <div class="ctrl"><label>사업부</label><select id="div">
   <option value="ALL">전체</option><option value="MX">MX</option><option value="VD">VD</option><option value="DA">DA</option></select></div>
 <div class="ctrl"><label>기간</label>
  <select id="ptype">
   <option value="day">일</option><option value="week">주</option><option value="month">월</option>
   <option value="quarter">분기</option><option value="year">연</option>
   <option value="mtd">이번 달 누적</option><option value="qtd">이번 분기 누적</option>
   <option value="ytd" selected>올해 누적</option>
  </select>
 </div>
 <div class="ctrl" id="pickerWrap"></div>
 <div class="ctrl"><label>비교</label><select id="cmpBasis"></select></div>
 <div class="spacer"></div>
 <input type="file" id="trafficFile" accept=".csv" style="display:none">
 <button class="btn" id="uploadBtn" title="국가,날짜,트래픽 형식의 CSV. 브라우저에서만 처리되며 저장되지 않습니다.">실측 트래픽 올리기</button>
 <button class="btn" id="clearTrafficBtn">지우기</button>
 <button class="btn" id="csvbtn">CSV 내보내기</button>
 <div class="rowbreak"></div>
 <div id="periodSummary" class="foot"></div>
 <div id="csvStatus" class="foot"></div>
 <!-- Resolved period bounds. The chips above are the control surface; these
      hold the actual dates every calculation reads, so they stay in the DOM
      but never render. -->
 <input type="hidden" id="csd" value="__DEF_CMP_FROM__">
 <input type="hidden" id="ced" value="__DEF_CMP_TO__">
 <input type="hidden" id="sd" value="__DEF_CUR_FROM__">
 <input type="hidden" id="ed" value="__DEF_CUR_TO__">
</div>

<div class="wrap">

  <div class="cards" id="cards"></div>

  <div class="split">
    <div class="panel">
      <div class="phead">
        <div class="ptitle">트래픽 추세<span class="psub" id="tsub"></span></div>
        <div class="legend" id="legend"></div>
      </div>
      <div style="position:relative;height:236px"><canvas id="trend"></canvas></div>
      <div class="note" id="tnote"></div>
    </div>

    <div class="panel" id="axisPanel">
      <div class="phead"><div class="ptitle">3축 진단<span class="psub" id="axisBasis"></span></div></div>
      <div class="tsum" id="axisSum3"></div>
      <div id="axisRows"></div>
      <div class="contrib" id="axisContrib"></div>
    </div>
  </div>

  <div>
    <div class="phead" style="margin-bottom:10px">
      <div class="ptitle">외부 요인<span class="psub" id="evcount"></span></div>
    </div>
    <div class="split">
      <div class="evlist">
        <div class="evstrip">
          <div class="fgroup"><span class="flbl">방향</span>
            <div class="seg" id="segDir">
              <button data-v="ALL" class="on">전체</button>
              <button data-v="+">▲ 증가</button>
              <button data-v="-">▼ 감소</button>
            </div></div>
          <div class="fgroup"><span class="flbl">축</span>
            <div class="seg" id="segAxis">
              <button data-v="ALL" class="on">전체</button>
              <button data-v="demand">수요</button>
              <button data-v="share">점유</button>
              <button data-v="supply">공급</button>
            </div></div>
          <div class="fgroup"><span class="flbl">정렬</span>
            <div class="seg" id="segSort">
              <button data-v="date" class="on">최신순</button>
              <button data-v="strength">영향강도순</button>
            </div></div>
        </div>
        <div id="list"></div>
      </div>
      <div class="detail" id="detail"></div>
    </div>
    <div class="foot">이벤트는 samsung.com 관련성 기준으로 자동 수집·필터링됩니다. 3축 분해는 인과 입증이 아니라 정황 분해입니다.</div>
  </div>

</div><!-- /wrap -->
</div><!-- /tab-board -->

<div id="tab-glossary" class="tabpane">
  <div class="wrap" id="glossary"></div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/chartjs-plugin-annotation/3.0.1/chartjs-plugin-annotation.min.js"></script>
<script>
const EV=__DATA__;
// "전체" is a scope VALUE, not a computed label: an event says either that it
// applies everywhere or which countries it is about. Nothing to derive.
const SCOPE_ALL="전체";
const WIKI_FILE=__WIKI__;
const CRUX=__CRUX__;
const SCORES=__SCORES__;
const AGREE=__AGREE__;
// Built from the countries the stored events actually name (see build.py
// country_tables()), not a fixed list: an event scoped to CN or JP used to be
// unreachable because the filter had no such option. The twelve tracked
// markets are always offered even on a day none of them appears.
// Which countries each region name covers. An event whose scope is "유럽" —
// the article named the bloc and not its members — has to show up under
// 독일 as well, and this is what lets the filter know that.
const REGION_MEMBERS=__REGION_MEMBERS__;
// Dropdown groups, in order. 한국 is its own group (home market, not one of
// 동아시아) and 아시아 is absent because it overlaps three groups that are
// present — it still works as a stored scope value and still matches through
// REGION_MEMBERS.
const REGION_GROUPS=__REGION_GROUPS__;
// Always offered, even on a day no event names them, so the dropdown does not
// shrink and grow underfoot.
const PINNED=__PINNED__;
// The filter lists are derived from EV at load time, not baked in at build
// time: the countries on offer are exactly the countries the events in front
// of you name. A country that appears for the first time today shows up
// today, and one that only ever appeared in a since-removed event stops being
// offered — without anyone maintaining a list.
function countryTables(events){
 const named=new Set(PINNED), regionUsed=new Set();
 for(const e of events){
  for(const t of String(e.scope||'').split(';')){
   if(!t||t===SCOPE_ALL) continue;
   (REGION_MEMBERS[t]?regionUsed:named).add(t);
  }
 }
 const regions={"ALL":null}, ordered=[];
 for(const [name,members] of REGION_GROUPS){
  const got=members.filter(c=>named.has(c));
  // A region whose countries are never named individually still belongs in
  // the list when an event is scoped to the region itself.
  if(got.length||regionUsed.has(name)){ regions[name]=got.length?got:members.slice(); ordered.push(...got); }
 }
 const claimed=new Set(REGION_GROUPS.flatMap(([,m])=>m));
 const unclaimed=[...named].filter(c=>!claimed.has(c)).sort();
 if(unclaimed.length){ regions["기타"]=unclaimed; ordered.push(...unclaimed); }
 const seen=new Set(), countries=[["ALL","전체"]];
 for(const c of ordered){ if(!seen.has(c)){ seen.add(c); countries.push([c,c]); } }
 return {regions,countries};
}
const __ct=countryTables(EV);
const REGIONS=__ct.regions, COUNTRIES=__ct.countries;
const DIV2COMP={MX:["Apple","Xiaomi","vivo","OPPO"],VD:["LG","TCL","Hisense"],DA:["LG","Whirlpool","Bosch"]};
const ALL_DIVS=["MX","VD","DA"];
// Scope is stored as it reads — "전체" or Korean country names — so the label
// is the value with the separator spaced out.
function scopeLabelKo(scope){
 const arr=(scope||'').split(';').filter(x=>x);
 return arr.length?arr.join(', '):'—';
}
// Division label: 'all' if MX/VD/DA all present, '—' if none
function divLabel(divs){
 const arr=(divs||'').split(';').filter(x=>x);
 if(!arr.length) return '전체';
 if(ALL_DIVS.every(dd=>arr.includes(dd))) return '전체';
 return arr.join(', ');
}
const DIRC={"-":"#f2716a","+":"#43c07a","neutral":"#6f7580","unknown":"#6f7580"};
const DIRCLS={"-":"neg","+":"pos","neutral":"","unknown":""};
const STRENGTH=e=>Math.max(1,Math.min(5,+e.impact_strength||2));
// Show the article's host rather than the raw URL — collected URLs are often
// long tracking links that would blow out the card layout.
function hostOf(u){ try{ return new URL(u).hostname.replace(/^www\./,''); }catch(_){ return u; } }
const region=document.getElementById('region'),country=document.getElementById('country'),dv=document.getElementById('div'),sd=document.getElementById('sd'),ed=document.getElementById('ed'),csd=document.getElementById('csd'),ced=document.getElementById('ced');
const ptype=document.getElementById('ptype'),cmpBasis=document.getElementById('cmpBasis'),pickerWrap=document.getElementById('pickerWrap');

// ===== Flexible period selector =====
// The option VALUES stay as the internal codes shiftPeriod() switches on;
// only what the reader sees is Korean.
const BASIS_KO={DoD:'전일 대비',WoW:'전주 대비',MoM:'전월 대비',QoQ:'전분기 대비',YoY:'전년 동기'};
const PERIOD_PAIRS={
  day:["DoD","WoW","YoY"],
  week:["WoW","YoY"],
  month:["MoM","YoY"],
  quarter:["QoQ","YoY"],
  year:["YoY"],
  mtd:["MoM","YoY"],
  qtd:["QoQ","YoY"],
  ytd:["YoY"],
};
const MON_KO=["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];
function _isoDate(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function _wikiToday(){const s=wikiSeries("Samsung");return s.length?new Date(s[s.length-1].date+'T00:00'):new Date();}
function _yearOpts(sel){let o='';const ty=_wikiToday().getFullYear();for(let y=ty-2;y<=ty;y++)o+=`<option${y===sel?' selected':''}>${y}</option>`;return o;}
function buildPicker(t){
  const ty=_wikiToday();
  const lbl=s=>`<label>${s}</label>`;
  if(t==='day'||t==='week') return lbl(t==='week'?'주 (해당 주 아무 날)':'날짜')+`<input type="date" id="pv" value="${_isoDate(ty)}">`;
  if(t==='month') return lbl('연 · 월')+`<div style="display:flex;gap:6px"><select id="py">${_yearOpts(ty.getFullYear())}</select><select id="pm">${MON_KO.map((m,i)=>`<option value="${i}"${i===ty.getMonth()?' selected':''}>${m}</option>`).join('')}</select></div>`;
  if(t==='quarter') return lbl('연 · 분기')+`<div style="display:flex;gap:6px"><select id="py">${_yearOpts(ty.getFullYear())}</select><select id="pq">${[1,2,3,4].map(q=>`<option value="${q-1}"${(q-1)===Math.floor(ty.getMonth()/3)?' selected':''}>${q}분기</option>`).join('')}</select></div>`;
  if(t==='year') return lbl('연도')+`<select id="py" style="width:100%">${_yearOpts(ty.getFullYear())}</select>`;
  return `<label>&nbsp;</label><div style="font-size:11px;color:var(--muted);padding-top:9px">오늘(${_isoDate(ty)}) 기준 · 추가 입력 불필요</div>`;
}
function currentPeriod(t){
  const g=id=>document.getElementById(id), ty=_wikiToday();
  const y=ty.getFullYear(),m=ty.getMonth(),d=ty.getDate();
  if(t==='day'){const x=new Date(g('pv').value+'T00:00');return [x,x];}
  if(t==='week'){const x=new Date(g('pv').value+'T00:00');const s=new Date(x);s.setDate(x.getDate()-6);return [s,x];}
  if(t==='month'){const yy=+g('py').value,mm=+g('pm').value;return [new Date(yy,mm,1),new Date(yy,mm+1,0)];}
  if(t==='quarter'){const yy=+g('py').value,q=+g('pq').value,qs=q*3;return [new Date(yy,qs,1),new Date(yy,qs+3,0)];}
  if(t==='year'){const yy=+g('py').value;return [new Date(yy,0,1),new Date(yy,11,31)];}
  if(t==='mtd')return [new Date(y,m,1),new Date(y,m,d)];
  if(t==='qtd'){const qs=Math.floor(m/3)*3;return [new Date(y,qs,1),new Date(y,m,d)];}
  return [new Date(y,0,1),new Date(y,m,d)]; // ytd
}
function shiftPeriod(range,basis){
  const sh=dt=>{const x=new Date(dt);
    if(basis==='DoD')x.setDate(x.getDate()-1);
    else if(basis==='WoW')x.setDate(x.getDate()-7);
    else if(basis==='MoM')x.setMonth(x.getMonth()-1);
    else if(basis==='QoQ')x.setMonth(x.getMonth()-3);
    else if(basis==='YoY')x.setFullYear(x.getFullYear()-1);
    return x;};
  return [sh(range[0]),sh(range[1])];
}
function applyPeriod(){
  const t=ptype.value, basis=cmpBasis.value;
  const cur=currentPeriod(t), cm=shiftPeriod(cur,basis);
  sd.value=_isoDate(cur[0]); ed.value=_isoDate(cur[1]);
  csd.value=_isoDate(cm[0]); ced.value=_isoDate(cm[1]);
  const sumEl=document.getElementById('periodSummary');
  if(sumEl){
   const single=cur[0].getTime()===cur[1].getTime();
   const curTxt=single?_isoDate(cur[0]):`${_isoDate(cur[0])} ~ ${_isoDate(cur[1])}`;
   const cmTxt=single?_isoDate(cm[0]):`${_isoDate(cm[0])} ~ ${_isoDate(cm[1])}`;
   sumEl.innerHTML=`비교 <strong style="color:var(--ink)">${cmTxt}</strong> &nbsp;→&nbsp; 현재 <strong style="color:var(--accent)">${curTxt}</strong>`;
  }
}
function refreshPeriod(){
  const t=ptype.value;
  pickerWrap.innerHTML=buildPicker(t);
  pickerWrap.querySelectorAll('input,select').forEach(el=>el.onchange=()=>{applyPeriod();showAll=false;render();});
  cmpBasis.innerHTML=PERIOD_PAIRS[t].map((p,i)=>`<option value="${p}"${i===PERIOD_PAIRS[t].length-1?' selected':''}>${BASIS_KO[p]||p}</option>`).join('');
  applyPeriod(); showAll=false; render();
}
const CONFW={high:3,med:2,low:1};
let showAll=false;  // 'show more' expanded state


// Verdict: % change of Samsung average views, comparison period vs current period
function trendVerdict(){
 // Needs all four dates (current + comparison)
 if(!(csd.value && ced.value && sd.value && ed.value)) return null;
 const sam=samSeries(); if(!sam.length) return null;
 const avg=(from,to)=>{
  const vals=sam.filter(p=>p.date>=from && p.date<=to).map(p=>p.views);
  return vals.length? vals.reduce((a,b)=>a+b,0)/vals.length : null;
 };
 const baseAvg=avg(csd.value, ced.value);
 const curAvg=avg(sd.value, ed.value);
 if(baseAvg==null || curAvg==null || baseAvg===0) return null;
 const pct=(curAvg-baseAvg)/baseAvg*100;
 return {pct, dir: pct<0?'-':(pct>0?'+':'neutral'),
         baseFrom:csd.value, baseTo:ced.value, curFrom:sd.value, curTo:ed.value};
}
// Same idea as trendVerdict(), but for the competitor aggregate — lets us tell
// "market-wide" moves (competitors moved the same direction) apart from
// "samsung.com-only" moves (competitors didn't).
function compVerdict(){
 if(!(csd.value && ced.value && sd.value && ed.value)) return null;
 const names=compNames(); if(!names.length) return null;
 const avgSum=(from,to)=>{
  let total=0, any=false;
  names.forEach(n=>{
   const vals=wikiSeries(n).filter(p=>p.date>=from&&p.date<=to).map(p=>p.views);
   if(vals.length){ any=true; total+=vals.reduce((a,b)=>a+b,0)/vals.length; }
  });
  return any?total:null;
 };
 const baseAvg=avgSum(csd.value, ced.value);
 const curAvg=avgSum(sd.value, ed.value);
 if(baseAvg==null || curAvg==null || baseAvg===0) return null;
 const pct=(curAvg-baseAvg)/baseAvg*100;
 return {pct, dir: pct<0?'-':(pct>0?'+':'neutral')};
}
region.innerHTML=Object.keys(REGIONS).map((r,i)=>`<option value="${r}"${i===0?' selected':''}>${r==='ALL'?'전체':r}</option>`).join('');
function syncCountries(){const reg=REGIONS[region.value];
 const list=reg?COUNTRIES.filter(c=>c[0]==='ALL'||reg.includes(c[0])):COUNTRIES;
 country.innerHTML=list.map((c,i)=>`<option value="${c[0]}"${i===0?' selected':''}>${c[1]}</option>`).join('');}
syncCountries();
// When a country is picked, switch the region to that country's region
function regionOfCountry(code){
 for(const[rk,arr]of Object.entries(REGIONS)){ if(arr && arr.includes(code)) return rk; }
 return 'ALL';
}
function onCountryChange(){
 const picked=country.value;
 if(picked!=='ALL'){
  const rk=regionOfCountry(picked);
  if(region.value!==rk){
   region.value=rk;
   // Rebuild the country list for the new region but keep the selection
   const reg=REGIONS[rk];
   const list=reg?COUNTRIES.filter(c=>c[0]==='ALL'||reg.includes(c[0])):COUNTRIES;
   country.innerHTML=list.map(c=>`<option value="${c[0]}"${c[0]===picked?' selected':''}>${c[1]}</option>`).join('');
  }
 }
 showAll=false; render();
}
function activeCountrySet(){if(country.value!=='ALL')return [country.value];const reg=REGIONS[region.value];return reg?reg:null;}
// Every active filter — region/country, division, and the selected period —
// applied in one place, newest first.
function rows(){let r=EV.slice();
 // Country/region: a specific value keeps events containing any of them; 'all' = no filter (union)
 const cs=activeCountrySet();
 // An event scoped 전체 applies everywhere, so it belongs to every country's
 // and region's view — filtering it out would hide the majority of the ledger
 // the moment a country is picked.
 if(cs){ r=r.filter(e=>{const sc=(e.scope||'').split(';');
   if(sc.includes(SCOPE_ALL)) return true;          // applies everywhere
   if(cs.some(c=>sc.includes(c))) return true;      // names the country
   // scope is a region: does it contain any of the selected countries?
   return sc.some(t=>(REGION_MEMBERS[t]||[]).some(c=>cs.includes(c)));}); }
 // Division: specific value = contains it; 'all' = no filter
 if(dv.value!=='ALL'){ r=r.filter(e=>(e.divisions||'').split(';').includes(dv.value)); }
 if(sd.value)r=r.filter(e=>(e.date||'')>=sd.value);
 if(ed.value)r=r.filter(e=>(e.date||'')<=ed.value);
 return r.sort((a,b)=>(b.date||'').localeCompare(a.date||''));}

// ---- trend graph ----
function wikiSeries(brand){return (WIKI_FILE.series&&WIKI_FILE.series[brand])||[];}

// ===== Uploaded real-traffic series (in-memory only, never persisted) =====
// CSV format: country,date,traffic (daily). Parsed in-browser; cleared on refresh.
let UPLOADED_TRAFFIC=null;  // {raw:[{country,date,traffic}], countries:Set}
// Aliases: map common CSV country codes to our internal codes.
// (UK -> GB; MX -> MX_C, since MX is reserved for the Apple division code.)
const COUNTRY_ALIAS={UK:'GB', MX:'MX_C', GBR:'GB', USA:'US', KOR:'KR'};
function _normCountry(c){
 const u=(c||'').trim().toUpperCase();
 return COUNTRY_ALIAS[u]||u;
}
function parseTrafficCSV(text){
 text=text.replace(/^\uFEFF/,'');  // strip BOM if present
 const lines=text.split(/\r?\n/).filter(l=>l.trim());
 if(!lines.length) return null;
 // detect header
 let start=0;
 const first=lines[0].toLowerCase();
 if(first.includes('date')||first.includes('날짜')||first.includes('country')||first.includes('국가')||first.includes('traffic')) start=1;
 const rows=[]; const countries=new Set();
 for(let i=start;i<lines.length;i++){
  const parts=lines[i].split(',').map(s=>s.trim());
  if(parts.length<3) continue;
  const country=_normCountry(parts[0]), date=parts[1], traffic=parts[2];
  const v=parseFloat(traffic.replace(/[^0-9.\-]/g,''));
  // normalize date to YYYY-MM-DD
  let d=date.replace(/\//g,'-');
  const m=d.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if(m) d=`${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  if(!country||!d||isNaN(v)) continue;
  rows.push({country, date:d, traffic:v}); countries.add(country);
 }
 return rows.length?{raw:rows, countries}:null;
}
// Aggregate uploaded traffic for the currently selected country filter, as
// [{date,views}] so analysis code can treat it exactly like a wiki series.
function uploadedSeriesForFilter(){
 if(!UPLOADED_TRAFFIC) return null;
 const cv=country.value;  // 'ALL' or an internal country code (e.g. 'GB','MX_C')
 const byDate={};
 UPLOADED_TRAFFIC.raw.forEach(r=>{
  if(cv!=='ALL' && r.country!==cv) return;  // r.country already normalized to internal code
  byDate[r.date]=(byDate[r.date]||0)+r.traffic;
 });
 const out=Object.keys(byDate).sort().map(d=>({date:d, views:byDate[d]}));
 return out.length?out:null;
}
// Unified traffic source: uploaded real traffic if present, else wiki proxy.
function samSeries(){
 const up=uploadedSeriesForFilter();
 return up||wikiSeries("Samsung");
}
function trafficSourceLabel(){ return UPLOADED_TRAFFIC?'실제 트래픽(업로드)':'위키 조회수(대리지표)'; }
function compNames(){
 if(dv.value==='ALL'){
   const all=Object.values(DIV2COMP).flat();
   return all.filter((v,i)=>all.indexOf(v)===i);  // dedupe (LG appears in VD & DA)
 }
 return DIV2COMP[dv.value]||[];
}
function compLabel(){const n=compNames();return n.length>1?'경쟁사 합산':(n[0]||'');}
let chart;
// Custom plugin drawing event pins (circle body + tail + glowing anchor + connector)
// A numbered disc sitting ON the line, with a dashed drop line to the floor —
// the marker from the design. It punches a hole in the series by filling with
// the panel colour first, so the line never runs through the number.
const pinPlugin={
 id:'pins',
 afterDatasetsDraw(c){
  const ctx=c.ctx, y=c.scales.y, pins=c._pins||[];
  pins.forEach(p=>{
   const x=c.scales.x.getPixelForValue(p.xLabel);
   const py=y.getPixelForValue(p.anchorY);
   if(x==null||isNaN(x)||py==null||isNaN(py)) return;
   // The pin carries the event's row number, which runs into three digits on
   // a wide period — grow the disc rather than letting the label spill out.
   const R=String(p.n).length>2?11.5:9;
   ctx.save();
   ctx.strokeStyle=C_PINLINE; ctx.lineWidth=1; ctx.setLineDash([2,3]);
   ctx.beginPath(); ctx.moveTo(x,py+R); ctx.lineTo(x,y.bottom); ctx.stroke();
   ctx.setLineDash([]);
   ctx.beginPath(); ctx.arc(x,py,R,0,Math.PI*2);
   ctx.fillStyle=C_PANEL; ctx.fill();
   ctx.strokeStyle=p.color; ctx.lineWidth=1.5; ctx.stroke();
   ctx.fillStyle=p.color; ctx.font="500 9.5px 'IBM Plex Mono',monospace";
   ctx.textAlign='center'; ctx.textBaseline='middle';
   ctx.fillText(String(p.n),x,py+0.5);
   ctx.restore();
  });
 }
};
// Clicking a pin scrolls to the matching numbered card and highlights it
// Both jump helpers now SELECT rather than scroll to a card: the detail pane
// is where an event's full text lives, so pointing at one means putting it
// there. Row n still gets a flash so the eye finds it in the list.
function scrollToCard(n){
 let el=document.getElementById('evt-'+n);
 if(!el && !showAll){ showAll=true; render(); el=document.getElementById('evt-'+n); }
 if(!el) return;
 const id=el.dataset.id; if(id && id!==SEL){ SEL=id; render(); el=document.getElementById('evt-'+n); }
 if(!el) return;
 el.scrollIntoView({behavior:'smooth',block:'center'});
 el.classList.add('flash');
 setTimeout(()=>el.classList.remove('flash'),1600);
}
// ---- master list row + detail pane ---------------------------------------
// The list carries only what you scan by (direction, title, one-line summary,
// date, axis/strength); everything else lives in the detail pane, so a row
// stays one glance high and the pane can afford the metadata the list has no
// room for. Clicking a row selects it; the pane follows.
let FDIR='ALL', FAXIS='ALL', FSORT='date', SEL=null;

function evRowHtml(e, n){
 const cls=DIRCLS[e.impact_direction]||'';
 const on=(SEL===e.event_id)?' on':'';
 const arrow=e.impact_direction==='+'?'▲':(e.impact_direction==='-'?'▼':'―');
 const ax=axisOf(e);
 const summary=cleanDesc(e.description);
 return `<div class="evt ${cls}${on}" id="evt-${n}" data-id="${e.event_id}" onclick="selectEvent('${e.event_id}')">
   <span class="num">${String(n).padStart(2,'0')}</span>
   <span class="dir">${arrow}</span>
   <div><div class="ttl">${e.title||''}</div><div class="sum">${summary}</div></div>
   <div class="rt"><div class="date">${e.date||''}</div>
     <div class="meta">${AXIS_KO[ax]||''} · ${STRENGTH(e)}/5</div></div>
 </div>`;
}

// Source/filter markers were once written into description; strip them so the
// one-line summary is the sentence and nothing else.
function cleanDesc(d){
 return (d||'').replace(/\s*\[출처:[^\]]*\]/g,'').replace(/\s*\[filter:[^\]]*\]/g,'')
   .replace(/\s*\[source:[^\]]*\]/g,'').replace(/1차 출처 업데이트[^—]*—\s*/g,'')
   .replace(/원문:\s*/g,'').trim();
}

const DS_LABEL={url:'발행일 확인',llm:'기사 명시일',capture:'수집일 추정',seed:'수기 입력'};
const HORIZON_KO={immediate:'즉시 (며칠)',weeks:'수 주',months:'수 개월'};
const CONF_KO={high:'높음',med:'보통',low:'낮음'};

// The LLM's strength beside the 조정강도 — where the traffic move around this
// event ranked once the horizon elapsed. It is NOT this event's own effect:
// dozens of events are in flight at any moment and one traffic series cannot
// be divided among them, so the count of opposite-direction events live in the
// same window rides along and says so. Read from prediction_scores.json, never
// recomputed here and never written back over impact_strength.
const CALIB=(SCORES.strength_calibration||{});
function strengthTag(e){
 const p=STRENGTH(e);
 const o=(CALIB.per_event||{})[e.event_id];
 if(!o) return `<span class="tag">영향강도 ${p}/5</span>`;
 const d=o.observed-p;
 const col=Math.abs(d)>=2?'var(--warn)':'var(--muted)';
 const opp=o.opposing_overlap||0;
 const why=`LLM 판단 ${p} · horizon 경과 후 트래픽 변화 ${o.actual_pct>=0?'+':''}${o.actual_pct}%를 전체 5분위로 환산`
  +(opp?` · 같은 구간에 반대 방향 ${opp}건이 함께 있었으므로 이 사건 하나의 효과는 아닙니다`
       :` · 같은 구간에 반대 방향 이벤트 없음`);
 return `<span class="tag" title="${why}">`
  +`영향강도 ${p}/5 <span style="color:${col}">→ 조정강도 ${o.observed}</span></span>`
  +(opp?`<span class="tag" title="${why}" style="border-color:var(--warn)66;color:var(--warn)">반대 방향 ${opp}건 동시</span>`:'');
}

function detailHtml(e, n){
 if(!e) return `<div class="dhead"><span class="k">선택한 요인</span></div>
   <div class="foot">왼쪽 목록에서 요인을 고르면 전체 내용이 여기 표시됩니다.</div>`;
 const ax=axisOf(e);
 const dirWord=e.impact_direction==='+'?'증가 ▲':(e.impact_direction==='-'?'감소 ▼':'중립 ―');
 const dirCol=DIRC[e.impact_direction]||'var(--neu)';
 const url=String(e.raw_url||'');
 const tags=[`<span class="tag" style="border-color:${AXIS_COLOR[ax]}66;color:${AXIS_COLOR[ax]}">${AXIS_KO[ax]||'-'}</span>`,
   strengthTag(e),
   `<span class="tag">신뢰도 ${CONF_KO[e.confidence]||e.confidence||'-'}</span>`,
   `<span class="tag">${scopeLabelKo(e.scope)}</span>`].join('');
 const meta=[['영향 방향',`<span style="color:${dirCol}">${dirWord}</span>`],
   ['지속 기간',HORIZON_KO[e.impact_horizon]||e.impact_horizon||'-'],
   ['날짜 근거',DS_LABEL[e.date_source||'seed']||'-'],
   ['영향 사업부',divLabel(e.divisions)],
   ['판정 모델',e.llm||'-'],
   ['원문 출처',e.source||'-']]
   .map(([k,v])=>`<div class="kline"><span class="klbl">${k}</span><span class="metaval">${v}</span></div>`).join('');
 const acts=[/^https?:\/\//.test(url)?`<a class="btn" href="${url}" target="_blank" rel="noopener noreferrer">원문 열기 ↗</a>`:'',
   n?`<button class="btn" onclick="scrollToPin(${n})">추세에서 보기</button>`:''].filter(Boolean).join('');
 return `<div class="dhead"><span class="k">선택한 요인 / ${n?String(n).padStart(2,'0'):'-'}</span><span class="d">${e.date||''}</span></div>
  <div class="dttl">${e.title||''}</div>
  <div class="tags">${tags}</div>
  <div class="blk"><span class="blbl">요약 · 기사가 보도한 사실</span><div class="txt">${cleanDesc(e.description)||'—'}</div></div>
  ${e.impact?`<div class="blk inf"><span class="blbl">LLM 추론 · 모델의 판단</span><div class="txt">${e.impact}</div></div>`:''}
  <div>${meta}</div>
  ${acts?`<div class="dacts">${acts}</div>`:''}`;
}

function selectEvent(id){ SEL=id; render(); }
function scrollToPin(n){
 const c=document.getElementById('trend');
 if(c) c.scrollIntoView({behavior:'smooth',block:'center'});
}

function drawTrend(evSortedAsc, numByDate){
 const sam=wikiSeries("Samsung");
 const upSeries=uploadedSeriesForFilter();  // real traffic for current country filter, or null
 const hasCmp=!!(csd.value && ced.value);
 // Instead of one long line spanning comparison-start..current-end (which could be
 // many months/years apart), show CURRENT and COMPARISON periods as two lines aligned
 // by relative day position (1일차, 2일차, ...) — this keeps the visible x-axis span
 // as short as a single period, and makes the two periods directly overlay-comparable.
 function datesInRange(from,to){
  return sam.map(p=>p.date).filter(dt=>(!from||dt>=from)&&(!to||dt<=to));
 }
 const curDates=datesInRange(sd.value, ed.value);
 const cmpDates=hasCmp?datesInRange(csd.value, ced.value):[];
 const N=Math.max(curDates.length, cmpDates.length, 1);
 const xLabels=Array.from({length:N},(_,i)=>i+1);
 const valAt=(dates,ser,i)=>{ if(i>=dates.length) return null; const f=ser.find(p=>p.date===dates[i]); return f?f.views:null; };
 const curData=xLabels.map((_,i)=>valAt(curDates,sam,i));
 const cmpData=hasCmp?xLabels.map((_,i)=>valAt(cmpDates,sam,i)):[];
 // Competitor total: current period only (kept as context; not duplicated for the
 // comparison period, to avoid an overly busy chart).
 const names=compNames();
 const total=xLabels.map((_,i)=>{
  if(i>=curDates.length) return 0;
  return names.reduce((s,n)=>{const ser=wikiSeries(n);const f=ser.find(p=>p.date===curDates[i]);return s+(f?f.views:0);},0);
 });
 // Uploaded real traffic, aligned the same way as Samsung wiki above.
 const upAt=(dates,i)=>{ if(!upSeries||i>=dates.length) return null; const f=upSeries.find(p=>p.date===dates[i]); return f?f.views:null; };
 const upCurData=xLabels.map((_,i)=>upAt(curDates,i));
 const upCmpData=hasCmp?xLabels.map((_,i)=>upAt(cmpDates,i)):[];
 const hasUpload=upSeries&&(upCurData.some(v=>v!=null)||upCmpData.some(v=>v!=null));
 // Fit each scale to its own series instead of anchoring at zero. Wiki views
 // never approach zero, so a zero-based axis pressed every line flat against
 // the bottom of the panel and threw away the shape the chart exists to show.
 // No tick labels are printed (see the scales block), so there is no risk of
 // a reader misreading a truncated axis as a zero-based one.
 const span=(vals)=>{
  const v=vals.filter(x=>x!=null&&!isNaN(x));
  if(!v.length) return {};
  const lo=Math.min(...v), hi=Math.max(...v);
  const pad=(hi-lo||Math.abs(hi)||1)*0.18;
  return {min:lo-pad, max:hi+pad};
 };
 const ySpan=span([...curData,...cmpData]);
 const compSpan=span(total);
 const upSpan=span([...upCurData,...upCmpData]);
 // Format a YYYY-MM-DD date as "7/7" for x-axis ticks (current-period date at
 // that index; the comparison line's own real date still shows in tooltips).
 const fmtMD=(d)=>{ if(!d) return ''; const p=d.split('-'); return `${+p[1]}/${+p[2]}`; };
 // Pins: map CURRENT-period events onto the 현재 기간 line.
 //
 // Pinning every event does not work at this scale — a YTD view holds a few
 // hundred of them, the discs overlap into an unreadable band along the
 // bottom, and no single one can be clicked. So the chart marks only the
 // events strong enough to be worth looking for on a trend line: one per day
 // position (the strongest that day), then the PIN_LIMIT strongest overall.
 // Every event still has a numbered row in the list below — the pin is a
 // pointer INTO that list, not a second copy of it.
 const PIN_LIMIT=10;
 const byX=new Map();
 evSortedAsc.forEach((e)=>{
  if(!curDates.length || e.date<curDates[0] || e.date>curDates[curDates.length-1]) return;
  let nearIdx=0; for(let k=0;k<curDates.length;k++){ if(curDates[k]<=e.date) nearIdx=k; }
  const sv=curData[nearIdx];
  const cand={n:(numByDate&&numByDate[e.date])||'',xLabel:xLabels[nearIdx],
    anchorY:sv==null?0:sv,color:DIRC[e.impact_direction]||C_DIM,w:STRENGTH(e)};
  const prev=byX.get(nearIdx);
  if(!prev || cand.w>prev.w) byX.set(nearIdx,cand);
 });
 // Strongest first, but skip any pin that would land on top of one already
 // taken: two discs closer than ~1/24 of the axis overlap at this panel width.
 const minGap=Math.max(1,Math.round(N/24));
 const pins=[];
 [...byX.values()].sort((a,b)=>b.w-a.w).forEach(cand=>{
  if(pins.length>=PIN_LIMIT) return;
  if(pins.some(p=>Math.abs(p.xLabel-cand.xLabel)<minGap)) return;
  pins.push(cand);
 });
 pins.sort((a,b)=>a.xLabel-b.xLabel);
 // Swatches read straight off the chart palette — hard-coding them here is
 // how the legend silently drifted from the lines it labels.
 const lg=(c,t,dash)=>`<span style="display:flex;align-items:center;gap:5px"><span style="width:13px;height:2px;${dash?`border-top:2px dashed ${c}`:`background:${c}`};display:inline-block"></span>${t}</span>`;
 document.getElementById('legend').innerHTML=
  lg(C_SAM,'삼성')
  +(hasCmp?lg(C_DIM,'비교 기간',true):'')
  +lg(C_MKT,compLabel())
  +(hasUpload?lg(C_REAL,'실측'):'')
  +(hasUpload&&hasCmp?lg(C_REAL,'실측 비교',true):'');
 document.getElementById('tsub').textContent=hasCmp?`현재·비교 기간 일자 기준 · 각 ${N}일`:`현재 기간 ${N}일`;
 // Says what the line IS and what the pins mean — the two things a reader
 // cannot infer from the chart itself.
 const tn=document.getElementById('tnote');
 if(tn) tn.textContent = (upSeries?'실측 트래픽(업로드) 기준':'위키피디아 일별 조회수로 추정 · 실측 아님')
   + ' · 번호 핀은 아래 목록의 번호와 같은 요인입니다.';
 if(chart)chart.destroy();
 // Vertical fade under the primary line, as in the design. Built per draw
 // because the gradient needs the chart area's pixel height, which only
 // exists once Chart.js has laid the canvas out.
 // Gradient anchored to the SERIES, not to the panel. Spanning the whole
 // chart area put the opaque end at the top of the panel, so a line sitting
 // low in its scale got only the transparent tail and showed no fill at all.
 // Starting at the series' own high point keeps the wash directly under the
 // line wherever the line happens to sit.
 const fade=(hex)=>(ctx)=>{
  const a=ctx.chart.chartArea; if(!a) return 'transparent';
  const sc=ctx.chart.scales[ctx.dataset.yAxisID];
  const vals=(ctx.dataset.data||[]).filter(v=>v!=null&&!isNaN(v));
  let top=a.top;
  if(sc&&vals.length){
   const px=sc.getPixelForValue(Math.max(...vals));
   if(px!=null&&!isNaN(px)) top=Math.max(a.top,Math.min(px,a.bottom-1));
  }
  const g=ctx.chart.ctx.createLinearGradient(0,top,0,a.bottom);
  g.addColorStop(0,hex+'3d'); g.addColorStop(1,hex+'00');
  return g;
 };
 // Thin strokes, one filled series, comparisons dashed and dimmed — the
 // reading order is current > comparison > context.
 const LINE={tension:0.3,pointRadius:0,pointHoverRadius:3,spanGaps:true};
 const dsets=[
   Object.assign({label:'삼성 현재 기간',data:curData,borderColor:C_SAM,
     backgroundColor:fade(C_SAM),fill:'origin',borderWidth:1.75,yAxisID:'y'},LINE)];
 if(hasCmp){
   dsets.push(Object.assign({label:'삼성 비교 기간',data:cmpData,borderColor:C_DIM,
     backgroundColor:'transparent',borderWidth:1.5,borderDash:[4,3],yAxisID:'y'},LINE));
 }
 dsets.push(Object.assign({label:compLabel()+' (현재)',data:total,borderColor:C_MKT,
   backgroundColor:'transparent',borderWidth:1.5,yAxisID:'yComp'},LINE));
 if(hasUpload){
   dsets.push(Object.assign({label:'실측 트래픽(현재)',data:upCurData,borderColor:C_REAL,
     backgroundColor:fade(C_REAL),fill:'origin',borderWidth:1.75,yAxisID:'yUpload'},LINE));
   if(hasCmp){
     dsets.push(Object.assign({label:'실측 트래픽(비교)',data:upCmpData,borderColor:C_REAL,
       backgroundColor:'transparent',borderWidth:1.5,borderDash:[4,3],yAxisID:'yUpload'},LINE));
   }
 }
 chart=new Chart(document.getElementById('trend'),{type:'line',
  data:{labels:xLabels,datasets:dsets},
  options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:16,right:4,left:2}},
   onClick:(evt)=>{
     const rect=evt.chart.canvas.getBoundingClientRect();
     const px=evt.x; const py=evt.y;
     const ps=evt.chart._pins||[];
     let best=null,bestD=1e9;
     ps.forEach(p=>{
      const x=evt.chart.scales.x.getPixelForValue(p.xLabel);
      const pinY=evt.chart.scales.y.getPixelForValue(p.anchorY);
      const dx=px-x, dy=py-pinY; const dist=Math.sqrt(dx*dx+dy*dy);
      if(dist<bestD){bestD=dist;best=p;}
     });
     if(best && bestD<24){ scrollToCard(best.n); }
   },
   plugins:{legend:{display:false},
     tooltip:{backgroundColor:'#1b1e22',borderColor:'#2c3138',borderWidth:1,
       titleColor:'#b9bec6',bodyColor:'#e6e9ee',displayColors:false,padding:9,
       titleFont:{family:MONO,size:10},bodyFont:{size:11.5},
       callbacks:{
       title:(items)=>(items[0]?items[0].label+'일차':''),
       label:(c)=>{
         const i=c.dataIndex; const lbl=c.dataset.label;
         const isCmp=lbl.indexOf('비교')>=0;
         const d=isCmp?(cmpDates[i]||''):(curDates[i]||'');
         return `${lbl}${d?' ('+d+')':''}: ${(c.parsed.y||0).toLocaleString()}회`;
       }}}},
   // Horizontal hairlines and mono date ticks only. The y scales carry three
   // different units (wiki views, competitor views, real traffic), so a
   // printed number on the edge would invite comparing values that are not
   // comparable — the levels live in the tooltip, the shape lives here.
   scales:{
     x:{ticks:{color:C_TICK,font:{family:MONO,size:9.5},maxTicksLimit:6,padding:6,
         callback:(v,i)=>fmtMD(curDates[i])},
        grid:{display:false},border:{display:false}},
     y:Object.assign({ticks:{display:false},border:{display:false},
        grid:{color:C_GRID,drawTicks:false}},ySpan),
     yComp:Object.assign({position:'right',ticks:{display:false},
        border:{display:false},grid:{display:false}},compSpan),
     yUpload:Object.assign({display:hasUpload,position:'right',ticks:{display:false},
        border:{display:false},grid:{display:false}},upSpan)}},
  plugins:[pinPlugin]});
 chart._pins=pins; chart.update();
}



// ===== 3-axis diagnosis (demand / share / supply) =====
// Decomposition frame: organic-traffic change = demand shift (how much the
// whole topic space is searched) x share shift (samsung.com's slice of it)
// x supply shift (indexing/site issues). Each event gets ONE primary axis so
// a drop can be triaged: demand -> market-wide causes, share -> competitor/
// search-result causes, supply -> crawl/site causes.
const AXIS_KO={demand:'수요',share:'점유',supply:'공급'};
const AXIS_COLOR={demand:'#4fbf8f',share:'#5ac8dc',supply:'#e0904a'};
// Chart palette. Chart.js takes plain strings, so the CSS custom properties
// are mirrored here rather than referenced — one place to change either way.
const MONO="'IBM Plex Mono',ui-monospace,monospace";
const C_SAM='#4fcdcd', C_MKT='#ac8e4e', C_REAL='#e66e5a',
      C_DIM='#5b646f', C_TICK='#5a5e62', C_GRID='#1f2225',
      C_PANEL='#15171a',        // panel fill — pin discs punch a hole in the line
      C_PINLINE='#454e58';      // the pin's dashed drop line
const SUPPLY_KW=['인덱싱','크롤링','indexing','crawling','다운타임','downtime','장애','outage','core web vitals','사이트 속도','robots.txt','sitemap'];
const OWN_KW=['samsung','galaxy','삼성','갤럭시'];
// Named-rival mentions — the signal that a platform/AI/marketing-category
// event is actually a SHARE-axis event (redistributes visibility/traffic
// between Samsung and a specific competitor) rather than a market-wide shift
// that touches everyone's traffic equally (DEMAND-axis). E.g. "Google AI
// Overviews now answer 60% of queries" cuts click-through for the whole web,
// not just samsung.com vs named rivals -> demand. "Apple's AI feature launch
// draws comparison-shopping traffic away from samsung.com" -> share.
const COMPETITOR_KW=['apple','xiaomi','vivo','oppo','lg','tcl','hisense','whirlpool','bosch',
  '아이폰','애플','샤오미','비보','오포','엘지','보쉬'];
const VALID_AXES=['demand','share','supply'];
function axisOf(e){
 // Prefer the LLM's own judgement (collected directly at classification
 // time, with full article context) when present; only events collected
 // before this field existed (axis=="" or missing) fall through to the
 // keyword/category heuristic below.
 if(VALID_AXES.includes(e.axis)) return e.axis;
 const t=((e.title||'')+' '+(e.impact||'')+' '+(e.description||'')).toLowerCase();
 if(SUPPLY_KW.some(k=>t.includes(k))) return 'supply';
 const c=e.category;
 if(c==='platform'||c==='AI'||c==='marketing')
  return COMPETITOR_KW.some(k=>t.includes(k)) ? 'share' : 'demand';
 // company: Samsung's own launches drive demand; competitor moves contest share
 if(c==='company') return OWN_KW.some(k=>t.includes(k))?'demand':'share';
 return 'demand'; // economy, holiday, culture, social_issue, geopolitics, regulation
}
function _wikiMaps(names){
 return names.map(n=>{const m={};wikiSeries(n).forEach(q=>m[q.date]=q.views);return m;});
}
// Whole-market attention: Samsung + selected-division competitors, summed per day
function marketTotalSeries(){
 const maps=_wikiMaps(compNames());
 return wikiSeries('Samsung').map(p=>({date:p.date,views:maps.reduce((s,m)=>s+(m[p.date]||0),p.views)}));
}
// Samsung's share of that attention, as a % per day
function shareSeries(){
 const maps=_wikiMaps(compNames());
 return wikiSeries('Samsung').map(p=>{
  const tot=maps.reduce((s,m)=>s+(m[p.date]||0),p.views);
  return {date:p.date,views:tot?p.views/tot*100:null};
 }).filter(p=>p.views!=null);
}
function avgInRange(ser,from,to){
 const vals=ser.filter(p=>(!from||p.date>=from)&&(!to||p.date<=to)).map(p=>p.views);
 return vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null;
}
const dayMs=86400000;
const isoAdd=(iso,n)=>new Date(new Date(iso+'T00:00:00Z').getTime()+n*dayMs).toISOString().slice(0,10);
const isoDiff=(a,b)=>Math.round((new Date(a+'T00:00:00Z')-new Date(b+'T00:00:00Z'))/dayMs);
const median=a=>{if(!a.length)return null;const s=a.slice().sort((x,y)=>x-y),m=s.length>>1;
 return s.length%2?s[m]:(s[m-1]+s[m])/2;};

// How much of a period-over-period change was simply DUE — seasonality, the
// weekly cycle, the standing trend. The attribution used to hand the whole
// observed change to the axes, so a change that would have happened anyway was
// still "explained" by whatever news happened to be lying around.
//
// Method (seasonal-naive, no libraries): replay the SAME comparison at the same
// lag repeatedly back through history and collect the ratios. Their median is
// what this period-over-period step normally does; the spread says how unusual
// this one is. Everything is measured on the same series being attributed, so
// no extra assumption is smuggled in.
function seasonalBaseline(ser, curFrom, curTo, cmpFrom, cmpTo, maxBack=10){
 if(!(ser&&ser.length&&curFrom&&curTo&&cmpFrom&&cmpTo)) return null;
 const lag=isoDiff(curFrom,cmpFrom), len=isoDiff(curTo,curFrom);
 if(lag<=0||len<0) return null;
 const earliest=ser[0].date, ratios=[];
 for(let k=1;k<=maxBack;k++){
  const cf=isoAdd(curFrom,-lag*k), ct=isoAdd(cf,len);
  const pf=isoAdd(cf,-lag),        pt=isoAdd(pf,len);
  if(pf<earliest) break;                       // ran out of history
  const a=avgInRange(ser,cf,ct), b=avgInRange(ser,pf,pt);
  if(a&&b) ratios.push(Math.log(a/b));         // logs: symmetric, and additive
 }
 if(ratios.length<3) return null;              // too few replays to trust
 const m=median(ratios);
 // Median absolute deviation -> a robust sigma (1.4826 makes MAD comparable to
 // a standard deviation for normal-ish data). Robust because a single freak
 // period should not widen the band enough to hide a real anomaly.
 const mad=median(ratios.map(r=>Math.abs(r-m)));
 return {expectedLog:m, sigma:(mad*1.4826)||null, n:ratios.length};
}
// ---- axis panel (the 420px column) ----------------------------------------
// The whole three-axis read-out lives here, beside the chart: three sentences
// saying what moved, the three single-axis effects, and how the move splits
// between them. Nothing about the axes renders anywhere else on the page.
function renderCompactAxis(attr, vd, axName, fmtSigned){
 const sum3=document.getElementById('axisSum3');
 const rowsEl=document.getElementById('axisRows');
 const conEl=document.getElementById('axisContrib');
 if(!sum3||!rowsEl||!conEl) return;
 const AX=['demand','share','supply'];

 if(!attr){
  sum3.innerHTML=`<div class="ln"><span class="n">–</span><span class="t">${
    vd?'변화가 미미하거나 시장 시계열이 두 기간을 덮지 못해 축별 분해를 할 수 없습니다.'
      :'기간 비교를 위해 현재·비교 기간이 모두 필요합니다.'}</span></div>`;
  rowsEl.innerHTML=''; conEl.innerHTML=''; return;
 }

 const word=attr.totalPct<0?'하락':'상승';
 const ranked=AX.slice().sort((a,b)=>Math.abs(attr.eff[b])-Math.abs(attr.eff[a]));
 const lead=ranked[0], rest=ranked.slice(1);
 const pp=(k)=>fmtSigned(attr.eff[k]*100,'%p',1);
 const lines=[
  `이번 기간 트래픽이 비교 기간보다 ${fmtSigned(attr.totalPct,'%',1)} 움직였습니다.`
   + (attr.base? ` 그중 ${fmtSigned(attr.expectedPct,'%',1)}는 계절성으로 예상되던 몫입니다.`:''),
  `가장 크게 움직인 축은 ${axName(lead)}(${pp(lead)})입니다`
   + (attr.drove(attr.gs[lead]) ? ` — ${word}을 만든 쪽입니다.` : ` — ${word}과 반대로 작용했습니다.`),
  rest.map(k=>`${axName(k)} ${pp(k)}`).join(', ')
   + (rest.some(k=>!attr.drove(attr.gs[k])) ? ' — 반대로 작용한 축은 변화를 완화했습니다.' : '입니다.'),
 ];
 sum3.innerHTML=lines.map((t,i)=>`<div class="ln"><span class="n">${i+1}</span><span class="t">${t}</span></div>`).join('');

 rowsEl.innerHTML=AX.map(k=>{
  const eff=attr.eff[k]*100, mx=Math.max(...AX.map(a=>Math.abs(attr.eff[a]*100)),0.001);
  const w=Math.max(3,Math.abs(eff)/mx*100);
  const col=eff<0?'var(--neg)':(eff>0?'var(--pos)':'var(--neu)');
  return `<div class="axrow"><div><div class="an">${axName(k)}</div>
     <div class="ae">${k.toUpperCase()}</div></div>
    <div class="axbar"><i style="width:${w.toFixed(1)}%;background:${col}"></i></div>
    <div class="axval" style="color:${col}">${fmtSigned(eff,'%',1)}</div></div>`;
 }).join('');

 // Contribution share: magnitude only, so an axis that pushed the other way
 // still shows the size of what it did — the sign is already on the row above.
 const absSum=AX.reduce((t,k)=>t+Math.abs(attr.eff[k]||0),0);
 const parts=AX.map(k=>({k,share:absSum?Math.abs(attr.eff[k])/absSum*100:0,eff:attr.eff[k]*100}))
   .sort((a,b)=>b.share-a.share);
 const COL={demand:'var(--pos)',share:'var(--accent)',supply:'var(--neg)'};
 const opposed=parts.filter(p=>p.share>0.5&&!attr.drove(attr.gs[p.k])).map(p=>axName(p.k));
 conEl.innerHTML=`<div class="chead"><span class="k">변화 기여 비중</span>
    <span class="v">전체 ${fmtSigned(attr.totalPct,'%',1)} 중</span></div>
   <div class="cbar">${parts.map(p=>`<div style="width:${p.share.toFixed(1)}%;background:${COL[p.k]}"></div>`).join('')}</div>
   ${parts.map(p=>`<div class="crow"><span class="cdot" style="background:${COL[p.k]}"></span>
     <span class="cn">${axName(p.k)}</span>
     <span class="cv">${p.share.toFixed(1)}%</span>
     <span class="cx">${fmtSigned(p.eff,'%p',1)}</span></div>`).join('')}
   <div class="note">부호를 뺀 크기 비중입니다${opposed.length?` — ${opposed.join('·')} 축은 반대 방향으로 작용했습니다.`:'.'}</div>`;
}

function renderAxisPanel(r,vd,numByDate){
 const panel=document.getElementById('axisPanel');
 if(!(csd.value&&ced.value&&sd.value&&ed.value)){panel.style.display='none';return;}
 const mkt=marketTotalSeries();
 const dCur=avgInRange(mkt,sd.value,ed.value), dCmp=avgInRange(mkt,csd.value,ced.value);

 // ---- Attribution: multiplicative decomposition of the traffic change ----
 // Basis: REAL uploaded traffic whenever one is loaded, wiki Samsung views
 // otherwise (samSeries() already encodes that preference) — every causal
 // read-out in the dashboard should describe real traffic when we have it.
 //
 // Identity:  traffic = market attention x capture
 //   market attention = wiki Samsung + wiki competitors (an INDEX — no free
 //     source of real competitor traffic exists, so this axis stays wiki even
 //     when the numerator is real traffic)
 //   capture = traffic / market attention, i.e. how much traffic a given
 //     level of market interest actually converts into. Defined as the LOG
 //     RESIDUAL (gC = gT - gM) rather than a separately averaged ratio, so
 //     the two effects multiply back to the observed change EXACTLY (an
 //     independently averaged ratio leaves a Jensen gap).
 const basisSer=samSeries();
 const tCur=avgInRange(basisSer,sd.value,ed.value), tCmp=avgInRange(basisSer,csd.value,ced.value);
 const isReal=!!UPLOADED_TRAFFIC && !!uploadedSeriesForFilter();
 // An upload that doesn't span BOTH periods can't be decomposed at all —
 // surfaced explicitly rather than silently falling back to a different basis.
 const basisGap=isReal && (tCur==null || !tCmp);
 const lcpSer=((CRUX.metrics||{}).lcp_ms)||[];
 let attr=null;
 if(tCur!=null && tCmp && dCur!=null && dCmp){
  const gT=Math.log(tCur/tCmp), gM=Math.log(dCur/dCmp);
  if(Math.abs(gT)>1e-6){
   let gC=gT-gM, gSu=0, lcpDelta=null;   // capture = residual -> exact by construction
   const lcpAsViews=lcpSer.map(p=>({date:p.date,views:p.p75}));
   const lCur=avgInRange(lcpAsViews,sd.value,ed.value), lCmp=avgInRange(lcpAsViews,csd.value,ced.value);
   if(lCur!=null&&lCmp){
    lcpDelta=(lCur-lCmp)/lCmp*100;
    // A CWV regression on a down-move carves part of the capture decline out
    // as a supply effect (capture is where site health would surface).
    if(lcpDelta>10 && gT<0 && gC<0){
     const frac=Math.min(0.25,(lcpDelta-10)/100);
     gSu=gC*frac; gC=gC-gSu;
    }
   }
   // Same sign as the total = drove it. gT = gM + gC + gSu, so at least one
   // axis always shares the total's sign; an empty causes list is impossible.
   const drove=g=>(gT<0?g<-1e-9:g>1e-9);
   const gs={demand:gM, share:gC, supply:gSu};
   const eff={};
   for(const k in gs) eff[k]=Math.exp(gs[k])-1;   // its own standalone effect
   // Split the observed move into the part this period-over-period step
   // normally produces (seasonality/trend) and the part that actually needs
   // explaining, so a routine seasonal dip is not read as news-driven.
   const base=seasonalBaseline(basisSer, sd.value, ed.value, csd.value, ced.value);
   let expectedPct=null, residualPct=null, z=null;
   if(base){
    expectedPct=(Math.exp(base.expectedLog)-1)*100;
    residualPct=(Math.exp(gT-base.expectedLog)-1)*100;
    if(base.sigma) z=(gT-base.expectedLog)/base.sigma;
   }
   attr={eff,gs,drove,lcpDelta,totalPct:(Math.exp(gT)-1)*100,
         base,expectedPct,residualPct,z};
  }
 }

 const fmtSigned=(v,unit,dec)=>v==null?'—':`${v>=0?'+':''}${v.toFixed(dec)}${unit}`;
 // The share axis means something different on each basis, so name it once
 // here and reuse everywhere.
 const shareName=isReal?'점유·전환':'점유';
 const axName=(ax)=>ax==='share'?shareName:AXIS_KO[ax];

 const basisEl=document.getElementById('axisBasis');
 if(basisEl) basisEl.textContent = basisGap ? '실측 트래픽이 비교 기간을 덮지 않음'
   : isReal ? '실측 트래픽 기준' : '위키 조회수 추정';
 renderCompactAxis(attr, vd, axName, fmtSigned);
 panel.style.display='block';
}

function render(){
 let r=rows();  // result after all active filters (region/country/division/KPI/period)
 const vd=trendVerdict();
 // Default ordering only — the list's own 정렬 segment overrides it below.
 // Trend-direction factors first, then confidence, neutral last, newest last.
 const confRank=e=>CONFW[e.confidence]||0;
 if(vd && vd.dir!=='neutral'){
  const dirMatch=e=> e.impact_direction===vd.dir ? 0 : (e.impact_direction==='neutral'?2:1);
  r.sort((a,b)=>
    dirMatch(a)-dirMatch(b)
    || confRank(b)-confRank(a)
    || ((a.impact_direction==='neutral'?1:0)-(b.impact_direction==='neutral'?1:0))
    || (b.date||'').localeCompare(a.date||''));
 } else if(vd){
  r.sort((a,b)=> confRank(b)-confRank(a) || ((a.impact_direction==='neutral'?1:0)-(b.impact_direction==='neutral'?1:0)) || (b.date||'').localeCompare(a.date||''));
 }

 const numByDate={}; r.forEach((e,i)=>{ if(!(e.date in numByDate)) numByDate[e.date]=i+1; });


 const evAsc=r.slice().sort((a,b)=>(a.date||'').localeCompare(b.date||''));
 // The chart comes from a CDN. If that script is blocked, drawTrend throws,
 // and everything after it here — KPI cards, the event list, the detail pane —
 // never runs, leaving a page that looks broken rather than one missing a
 // chart. The rest of the dashboard does not depend on Chart.js, so let it
 // render either way.
 try{ drawTrend(evAsc, numByDate); }
 catch(err){
  console.error('trend chart failed',err);
  const tn=document.getElementById('tnote');
  if(tn) tn.textContent='추세 차트를 불러오지 못했습니다 (차트 라이브러리 로드 실패) · 아래 목록과 3축 진단은 정상입니다.';
 }
 renderAxisPanel(r, vd, numByDate);

 // ---- KPI row ----------------------------------------------------------
 const sc=(SCORES.summary&&SCORES.summary.all)||{};
 const corr=SCORES.correlation||{};
 const hit=(sc.hit_rate!=null)?(sc.hit_rate*100).toFixed(1)+'%':'—';
 const fore=((SCORES.summary&&SCORES.summary.foreknown&&SCORES.summary.foreknown.hit_rate!=null)
   ? ' · 사전근거 '+(SCORES.summary.foreknown.hit_rate*100).toFixed(1)+'%':'');
 const trafVal=vd?((vd.pct>=0?'+':'')+vd.pct.toFixed(1)+'%'):'—';
 const trafCol=vd?(vd.dir==='-'?'var(--neg)':(vd.dir==='+'?'var(--pos)':'var(--neu)')):'var(--neu)';
 const kpi=[
  ['수집 이벤트', r.length, '', 'var(--ink)'],
  ['트래픽 변화', trafVal, vd?('vs 비교 기간'):'기간 비교 필요', trafCol],
  ['방향 적중률', hit, (sc.n?'n='+sc.n:'')+fore, 'var(--warn)'],
  ['누적 영향지수 상관', (corr.pressure_vs_forward_traffic_r!=null?'r '+corr.pressure_vs_forward_traffic_r.toFixed(3):'—'),
    (corr.n_days?'n='+corr.n_days+'일':''), 'var(--neu)'],
 ];
 document.getElementById('cards').innerHTML = kpi.map(([l,v,n,c])=>
   `<div class="card"><div class="lbl">${l}</div><div><span class="val" style="color:${c}">${v}</span>${n?`<span class="vnote">${n}</span>`:''}</div></div>`).join('');

 // ---- event list (direction / axis / sort apply here only, never to the
 // axis decomposition, which needs every event in the period) -------------
 let lr=r.slice();
 if(FDIR!=='ALL') lr=lr.filter(e=>e.impact_direction===FDIR);
 if(FAXIS!=='ALL') lr=lr.filter(e=>axisOf(e)===FAXIS);
 lr.sort(FSORT==='strength'
   ? (a,b)=>STRENGTH(b)-STRENGTH(a)||(b.date||'').localeCompare(a.date||'')
   : (a,b)=>(b.date||'').localeCompare(a.date||''));
 // suffix names which filter actually narrowed the set, so "필터 적용" never
 // shows up when nothing is filtered at all
 const _sfx = lr.length!==r.length ? ' · 목록 필터 적용'
            : r.length!==EV.length ? ' · 기간·지역 필터 적용' : '';
 document.getElementById('evcount').textContent = `${lr.length} / ${EV.length}건` + _sfx;

 const LIMIT=30;
 const shown=showAll?lr:lr.slice(0,LIMIT);
 const rowsHtml = lr.length
   ? shown.map((e,i)=>evRowHtml(e, i+1)).join('')
   : '<div class="empty">해당 조건에 맞는 이벤트가 없습니다.</div>';
 const moreBtn = (lr.length>LIMIT)
   ? `<div class="empty" style="padding:10px"><button class="btn" id="morebtn">${showAll?'접기':'더보기 ('+(lr.length-LIMIT)+'건)'}</button></div>` : '';
 document.getElementById('list').innerHTML = rowsHtml + moreBtn;
 const mb=document.getElementById('morebtn');
 if(mb) mb.onclick=()=>{ showAll=!showAll; render(); };

 // Selection: keep it if still visible, else fall back to the first row so
 // the pane is never blank while the list has content.
 let selEv=null, selNo=0;
 const selIdx=shown.findIndex(e=>e.event_id===SEL);
 if(selIdx>=0){ selEv=shown[selIdx]; selNo=selIdx+1; }
 else if(shown.length){ SEL=shown[0].event_id; selEv=shown[0]; selNo=1; }
 if(selNo){ const el=document.getElementById('evt-'+selNo); if(el) el.classList.add('on'); }
 document.getElementById('detail').innerHTML = detailHtml(selEv, selNo);
}

// ---- segmented filters ----------------------------------------------------
function wireSeg(id, set){
 const box=document.getElementById(id);
 box.querySelectorAll('button').forEach(b=>{
  b.onclick=()=>{
   box.querySelectorAll('button').forEach(x=>x.classList.remove('on'));
   b.classList.add('on'); set(b.dataset.v); showAll=false; render();
  };
 });
}
wireSeg('segDir', v=>FDIR=v);
wireSeg('segAxis', v=>FAXIS=v);
wireSeg('segSort', v=>FSORT=v);

// ---- glossary tab ---------------------------------------------------------
// Written once, here, rather than scattered as tooltips: someone meeting this
// dashboard for the first time needs the vocabulary in one place, and the
// "오해" line is where the field names that mislead get corrected.
const GLOSSARY=[
 {title:'AI가 사건마다 매기는 값', sub:'기사 한 건을 읽고 그 자리에서 붙이는 꼬리표입니다', terms:[
  {ko:'영향 방향',en:'DIRECTION',
   def:'이 사건 때문에 samsung.com 방문자가 늘지(▲) 줄지(▼)에 대한 AI의 판단입니다.',
   eg:'경쟁사가 신제품을 싸게 내놨다 → ▼ (우리 쪽 방문이 줄 것)'},
  {ko:'영향 강도',en:'STRENGTH 1–5',
   def:'그 영향이 얼마나 큰지를 1~5로 매긴 값입니다. 5가 가장 큽니다.',
   eg:'갤럭시 신제품 공개 = 5 · 해외 소매점 세일 기사 = 2',
   myth:'매출 크기가 아니라 웹사이트 방문자에 주는 크기입니다.'},
  {ko:'조정강도',en:'CALIBRATED STRENGTH',
   def:'그 요인이 예상한 기간이 다 지난 뒤, 그 무렵 트래픽이 실제로 얼마나 움직였는지를 '
      +'전체 요인과 견줘 1~5로 매긴 값입니다. 등수라서, 뒤에 새 요인이 쌓이면 같은 요인의 '
      +'등급이 한 칸 오르내릴 수 있습니다.',
   eg:'"영향강도 4/5 → 조정강도 2" = AI는 크게 볼 일이라 했지만, 그 무렵 움직임은 작은 축이었다는 뜻입니다.',
   myth:'그 요인 하나가 낸 효과가 아닙니다. 같은 기간에 반대로 미는 요인이 늘 수십 건 함께 '
       +'있어서, 트래픽 하나를 요인별 몫으로 나눌 수 없습니다. 그래서 옆에 "반대 방향 N건 동시"를 '
       +'같이 적습니다. AI가 매긴 영향 강도를 덮어쓰지도 않습니다 — 예측을 결과로 고쳐 쓰면 '
       +'그 예측이 맞았는지 더는 확인할 수 없기 때문입니다.'},
  {ko:'신뢰도',en:'CONFIDENCE',
   def:'AI가 자기 판단에 대해 갖는 확신입니다. 높음·보통·낮음 셋 중 하나입니다.',
   eg:'"방향이 ▼인 게 거의 확실하다" → 높음',
   myth:'기사가 사실인지 여부가 아닙니다. AI의 자기 확신도입니다.'},
  {ko:'지속 기간',en:'HORIZON',
   def:'영향이 언제까지 갈지입니다. 즉시(며칠) · 수 주 · 수 개월 중 하나입니다.',
   eg:'하루짜리 할인 = 즉시 · 검색엔진 정책 변화 = 수 개월'},
  {ko:'요약 / LLM 추론',en:'FACT / INFERENCE',
   def:'요약은 기사에 실제로 쓰인 사실이고, LLM 추론은 AI가 거기서 끌어낸 짐작입니다.',
   eg:'요약 "구글이 AI 검색을 도입했다" → 추론 "우리 사이트 유입이 줄 수 있다"',
   myth:'추론은 기사에 없는 내용입니다. 사실처럼 읽으면 안 됩니다.'},
  {ko:'날짜 근거',en:'DATE SOURCE',
   def:'이 사건의 날짜를 어디서 얻었는지입니다. 발행일 확인 · 기사 명시일 · 수집일 추정.',
   eg:'"수집일 추정"은 기사에서 날짜를 못 얻어 발견한 날로 채운 값입니다',
   myth:'"수집일 추정"인 건은 미리 예측했다는 근거가 될 수 없습니다.'},
 ]},
 {title:'대시보드가 스스로를 채점하는 값', sub:'지금까지 한 판단이 실제로 맞았는지 되돌아본 결과입니다', terms:[
  {ko:'방향 적중률',en:'HIT RATE',
   def:'▲/▼ 예측이 실제로 맞은 비율입니다. 기한이 다 지난 예측만 채점합니다.',
   eg:'__HIT_EG__',
   myth:'무조건 "증가"만 찍어도 올라가는 값이라, 숫자만 보고 판단하면 안 됩니다.'},
  {ko:'사전근거 한정',en:'FOREKNOWN',
   def:'날짜를 믿을 수 있는 사건만 골라 다시 잰 적중률입니다.',
   eg:'__FORE_EG__'},
  {ko:'누적 영향지수',en:'CUMULATIVE INDEX',
   def:'그날 사건들이 얼마나 세게 몰렸는지를 하나의 점수로 만든 값입니다.',
   eg:'큰 사건 3개가 겹친 날 = 높음. 시간이 지나면 점수가 줄어듭니다.'},
  {ko:'누적 영향지수 상관',en:'r',
   def:'지수가 높은 날 다음에 실제로 트래픽이 움직였는지를 −1~+1로 나타낸 값입니다.',
   eg:'__CORR_EG__',
   myth:'0에 가까우면 관계가 없다는 뜻이고, 표본이 적으면 값 자체를 믿을 수 없습니다.'},
  {ko:'순열검정 p값',en:'p-VALUE',
   def:'날짜를 마구 섞은 가짜 데이터로 1000번 계산해, 그중 몇 번이나 지금 결과만큼 그럴듯했는지입니다.',
   eg:'__P_EG__',
   myth:'작을수록(보통 0.05 미만) 우연이 아닐 가능성이 큽니다.'},
  {ko:'대리지표',en:'PROXY',
   def:'실제 방문자 수를 무료로 구할 수 없어 대신 쓰는 비슷한 숫자입니다.',
   eg:'지금은 위키피디아 "삼성" 문서 조회수를 씁니다. 실측 CSV를 올리면 그쪽으로 바뀝니다.',
   myth:'이것이 실제 samsung.com 방문자를 대변하는지는 아직 검증되지 않았습니다.'},
 ]},
 {title:'사건을 나누는 세 갈래', sub:'변화가 어디서 왔는지 구분하기 위한 분류입니다', terms:[
  {ko:'수요',en:'DEMAND',
   def:'시장 전체의 관심이 커지거나 작아진 몫입니다. 특정 경쟁사와의 다툼이 아닙니다.',
   eg:'연말 쇼핑 시즌, 스마트폰 시장 전체의 위축'},
  {ko:'점유·전환',en:'SHARE',
   def:'같은 관심 속에서 우리와 특정 경쟁사 사이에 방문이 옮겨간 몫입니다.',
   eg:'애플이 신제품을 내서 우리 쪽 검색이 줄어든 경우'},
  {ko:'공급',en:'SUPPLY',
   def:'samsung.com 사이트 자체의 문제입니다. 속도, 검색 노출, 장애.',
   eg:'사이트가 느려짐, 구글 검색에서 페이지가 빠짐',
   myth:'경쟁사 이야기는 절대 여기에 들어가지 않습니다.'},
  {ko:'변화 기여 비중',en:'CONTRIBUTION',
   def:'이번 기간 트래픽 변화를 세 축이 각각 몇 %씩 만들어냈는지입니다.',
   eg:'전체 +4.2% 중 수요가 65%, 점유가 29%, 공급이 6%',
   myth:'부호를 뺀 크기 비중입니다. 반대 방향으로 작용한 축의 몫도 함께 표시됩니다.'},
 ]},
];
function renderGlossary(){
 const box=document.getElementById('glossary'); if(!box) return;
 const sc=(SCORES.summary&&SCORES.summary.all)||{}, fk=(SCORES.summary&&SCORES.summary.foreknown)||{};
 const co=SCORES.correlation||{}, pm=(SCORES.permutation&&SCORES.permutation.all)||{};
 const fill={
  __HIT_EG__: sc.hit_rate!=null?`${sc.n}번 채점해 ${Math.round(sc.hit_rate*sc.n)}번 맞았습니다 → ${(sc.hit_rate*100).toFixed(1)}%. 동전던지기가 50%입니다.`:'아직 채점된 예측이 없습니다.',
  __FORE_EG__: fk.hit_rate!=null?`${fk.n}건 한정 ${(fk.hit_rate*100).toFixed(1)}% — 전체 ${sc.hit_rate!=null?(sc.hit_rate*100).toFixed(1)+'%':'—'}와 비교해 보십시오.`:'아직 해당 건이 없습니다.',
  __CORR_EG__: co.pressure_vs_forward_traffic_r!=null?`지금은 r ${co.pressure_vs_forward_traffic_r.toFixed(3)} (${co.n_days}일치 기준)입니다.`:'아직 계산되지 않았습니다.',
  __P_EG__: pm.p_value!=null?`p=${pm.p_value} → 가짜 데이터도 ${Math.round(pm.p_value*100)}%가 이만큼 나왔다는 뜻입니다.`:'아직 계산되지 않았습니다.',
 };
 const sub=t=>Object.keys(fill).reduce((x,k)=>x.split(k).join(fill[k]),t);
 box.innerHTML=`
  <div class="gintro">
    <div>
      <div style="font-size:19px;font-weight:600;letter-spacing:-0.015em;margin-bottom:8px">이 화면의 숫자를 읽는 법</div>
      <div style="font-size:13.5px;color:var(--ink-2);line-height:1.68">
        이 대시보드는 뉴스와 경쟁사 소식이 samsung.com 방문자에게 어떤 영향을 줄지
        <strong>AI가 매일 판단해 쌓아둔 기록</strong>입니다. 판단은 틀릴 수 있고, 그래서
        <strong>얼마나 맞았는지도 같이 기록</strong>합니다.
      </div>
    </div>
    <div class="panel">
      <div class="klbl" style="margin-bottom:10px">한 문장 요약</div>
      <div style="font-size:12.5px;color:var(--ink-2);line-height:1.7">
        <strong>"무슨 일이 있었나"</strong>는 기사에서 그대로 옮긴 <strong>사실</strong>이고,
        <strong style="color:var(--warn)">"그래서 어떻게 될까"</strong>는
        <strong style="color:var(--warn)">AI의 짐작</strong>입니다. 화면에서 이 둘은 항상 따로 표시됩니다.
      </div>
    </div>
  </div>`
  + GLOSSARY.map(g=>`
   <div>
     <div class="ghead"><div class="ptitle">${g.title}</div><div class="psub">${g.sub}</div></div>
     <div class="ggrid">${g.terms.map(t=>`
       <div class="gterm">
         <div class="gt"><span class="gko">${t.ko}</span><span class="gen">${t.en}</span></div>
         <div class="gdef">${sub(t.def)}</div>
         <div class="grow">
           <span class="gk">예시</span><span class="gv">${sub(t.eg)}</span>
           ${t.myth?`<span class="gk warn">오해</span><span class="gv warn">${sub(t.myth)}</span>`:''}
         </div>
       </div>`).join('')}</div>
   </div>`).join('')
  + `<div class="panel" style="border-left:2px solid var(--warn)">
      <div style="font-size:12.5px;font-weight:600;margin-bottom:7px">꼭 기억할 것 하나</div>
      <div style="font-size:12.5px;color:var(--ink-2);line-height:1.68">
        이 대시보드는 <strong>"무엇이 무엇을 일으켰다"를 증명하지 않습니다.</strong>
        같은 시기에 무슨 일이 있었고 방문자가 어떻게 움직였는지를 나란히 놓아, 사람이 판단할 재료를 주는 것까지가 역할입니다.
        <strong>이 숫자만 보고 결정을 내려서는 안 되며</strong> 실제 트래픽 데이터와 함께 봐야 합니다.
      </div>
    </div>`;
}
renderGlossary();

// ---- tabs -----------------------------------------------------------------
document.querySelectorAll('.tab').forEach(t=>{
 t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.tabpane').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('tab-'+t.dataset.tab).classList.add('active');
 };
});

function exportCSV(){const r=rows();
 const h=['date','scope','divisions','kpi','title','impact','description','impact_direction','confidence','llm','source','raw_title','raw_desc','raw_url'];
 const csv=[h.join(',')].concat(r.map(x=>h.map(k=>`"${(x[k]||'').toString().replace(/"/g,'""')}"`).join(','))).join('\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+csv,{type:'text/csv;charset=utf-8'}]));a.download='scom_external_factors.csv';a.click();}
document.getElementById('csvbtn').onclick=exportCSV;
region.onchange=()=>{showAll=false;syncCountries();render();};
country.onchange=onCountryChange;
[dv,sd,ed,csd,ced].forEach(el=>el.onchange=()=>{showAll=false;render();});
ptype.onchange=refreshPeriod; cmpBasis.onchange=()=>{applyPeriod();showAll=false;render();};
// Traffic CSV upload (in-memory only, never persisted)
const trafficFile=document.getElementById('trafficFile');
document.getElementById('uploadBtn').onclick=()=>trafficFile.click();
trafficFile.onchange=e=>{
 const f=e.target.files[0]; if(!f) return;
 const reader=new FileReader();
 reader.onload=ev=>{
  const parsed=parseTrafficCSV(ev.target.result);
  if(!parsed){ document.getElementById('csvStatus').textContent='CSV 형식을 읽지 못했습니다 (국가,날짜,트래픽 확인)'; return; }
  UPLOADED_TRAFFIC=parsed;
  const dates=parsed.raw.map(r=>r.date).sort();
  const days=new Set(dates).size;
  const from=dates[0], to=dates[dates.length-1];
  document.getElementById('csvStatus').innerHTML=`<span style="color:var(--pos)">● 실측 트래픽 사용 중</span> · ${parsed.countries.size}개국 · ${from}~${to} (${days}일, 저장 안 됨)`;
  showAll=false; render();
 };
 reader.readAsText(f,'utf-8');
 trafficFile.value='';  // allow re-upload of same file
};
document.getElementById('clearTrafficBtn').onclick=()=>{
 UPLOADED_TRAFFIC=null;
 document.getElementById('csvStatus').textContent='';
 showAll=false; render();
};
refreshPeriod();


</script></body></html>"""

LLM_LABELS={"ok":"정상 ✓","retired":"종료됨 — 모델 교체 필요","unknown":"키 없음",
            "error":"점검 실패 — 확인 필요"}
_LLM_DISPLAY=[("gemini","GEMINI"),("groq","GROQ"),("mistral","MISTRAL")]
_checked=str(mstat.get("last_checked","n/a"))
def _badge(name, label):
    s=_mstat_of(name)
    status=s.get("status","unknown")
    note=str(s.get("note","")).replace('"',"'")
    model=str(s.get("model","unknown"))
    lbl=LLM_LABELS.get(status,"상태 미상")
    # The top bar is one line, so the badge is the provider name and a dot;
    # the model id and the reason live in the tooltip where they do not
    # crowd out the timestamp.
    tip=f"{label} · {model} — {lbl}" + (f" ({note})" if note else "")
    return (f'<span class="mbadge {status}" title="{tip}"><span class="dot"></span>{label}</span>')
_feeds=read_json(FEED_HEALTH_FILE, {}).get("feeds", {})
_feed_ok=sum(1 for v in _feeds.values() if v.get("status")=="ok")
mbadges_html = "".join(_badge(n,l) for n,l in _LLM_DISPLAY) + (
    f'<span class="mbadge {"ok" if _feeds and _feed_ok==len(_feeds) else "error"}">'
    f'<span class="dot"></span>FEEDS {_feed_ok}/{len(_feeds)}</span>' if _feeds else "")

# The dashboard derives its own country/region dropdowns from the events at
# load time (see countryTables() in the page), so all Python sends is the
# vocabulary: which countries each region contains, which groups to offer, and
# which markets are always listed. Nothing here needs to know what today's
# events happen to say.
REGION_GROUPS = ([[name, members] for name, members in SCOPE_REGIONS.items()
                  if name != "아시아"] + [["한국", ["한국"]]])
PINNED = ["미국", "영국", "독일", "프랑스", "스페인", "포르투갈", "브라질",
          "멕시코", "호주", "인도", "튀르키예", "한국"]



HTML=(HTML.replace("__DATA__",json.dumps(events,ensure_ascii=False))
          .replace("__WIKI__",json.dumps(wiki,ensure_ascii=False))
          .replace("__CRUX__",json.dumps(crux,ensure_ascii=False))
          .replace("__SCORES__",json.dumps(scores,ensure_ascii=False))
          .replace("__AGREE__",json.dumps(agreement,ensure_ascii=False))
          .replace("__MBADGES__",mbadges_html)
          .replace("__DEF_CMP_FROM__",DEF_CMP_FROM)
          .replace("__DEF_CMP_TO__",DEF_CMP_TO)
          .replace("__DEF_CUR_FROM__",DEF_CUR_FROM)
          .replace("__DEF_CUR_TO__",DEF_CUR_TO)
          .replace("__REGION_MEMBERS__",json.dumps(SCOPE_REGIONS,ensure_ascii=False))
          .replace("__REGION_GROUPS__",json.dumps(REGION_GROUPS,ensure_ascii=False))
          .replace("__PINNED__",json.dumps(PINNED,ensure_ascii=False))
          .replace("__UPDATED__",updated))
open(INDEX_HTML,"w",encoding="utf-8").write(HTML)
print("built index.html with",len(events),"events, wiki series:",list(wiki.get("series",{}).keys()))
