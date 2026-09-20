// Dependency-free regression checks for the inline UI's chart and session logic.
// Run: node --test tests/web_ui.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync(new URL('../src/jevpip/web/index.html',`file://${__filename}`),'utf8');
const source=(start,end)=>html.slice(html.indexOf(start),html.indexOf(end,html.indexOf(start)));
function runtime(){
  const nodes=new Map();
  const $=id=>{
    if(!nodes.has(id))nodes.set(id,{value:'',checked:false,disabled:false,style:{},dataset:{},textContent:'',innerHTML:'',querySelectorAll(){return [];},options:[],add(option){this.options.push(option);}});
    return nodes.get(id);
  };
  $('instrument').value='USD_JPY';$('chart-interval').value='1min';$('mode').value='paper';
  const state={ready:true,config:{typesafe_api_key_configured:true},syncedSession:null};
  const context=vm.createContext({$,state,autoLimits:[],document:{querySelectorAll:()=>[...nodes.values()]},instrumentSpec(){return {price_decimals:0};},Option:function(text,value){this.text=text;this.value=value;},applyInstrumentDefaults(){},autopilotStyleChanged(){},autopilotChanged(){},modeChanged(){},updateTradeSummary(){},updateBacktestNote(){},updateStrategyBacktestSummary(){},applyProfile(name,p){state.restoredProfile=p;},applySignal(name,p){state.restoredSignal=p;}});
  vm.runInContext(source('function chartPrice(', 'window.addEventListener("resize"'),context);
  vm.runInContext(source('const paperFields=', 'function updateTradeSummary()'),context);
  vm.runInContext(source('const yen=', 'const pct='),context);
  vm.runInContext(source('function esc(s)', 'function renderCredentialState()'),context);
  vm.runInContext(source('function renderTopQuote(', 'async function start()'),context);
  vm.runInContext(source('function renderExecutions(', '\n$("autopilot").addEventListener'),context);
  return {context,$,state,nodes};
}
const bar=(time,close)=>({timestamp:new Date(time).toISOString(),open:close,high:close+1,low:close-1,close});

test('MA200 has all 180 visible values while warmup stays off screen',()=>{
  const {context:c}=runtime(),history=Array.from({length:400},(_,i)=>bar(i*60000,100+i));
  const merged=c.mergeChartPoints(history,[],'1min');
  assert.equal(merged.length,379);
  const visible=merged.slice(-180),averages=c.chartAverages(merged,200).slice(-180);
  assert.equal(visible.length,180);
  assert.equal(averages.length,180);
  assert.equal(averages[0],220.5);
  assert.equal(averages.at(-1),399.5);
  assert.ok(averages.every(Number.isFinite));
});

test('live ticks merge into the selected candle without fabricating gap candles',()=>{
  const {context:c}=runtime(),history=[bar(0,100),bar(300000,110)];
  const merged=c.mergeChartPoints(history,[{timestamp:new Date(42000).toISOString(),bid:102,ask:104},{timestamp:new Date(59000).toISOString(),mid:99}],'5min');
  assert.equal(merged.length,2);
  assert.equal(merged[0].open,100);
  assert.equal(merged[0].high,103);
  assert.equal(merged[0].close,99);
  assert.equal(c.chartPrice({close:null}),null);
  assert.equal(c.chartPrice({bid:null,ask:10}),null);
  assert.equal(c.chartPrice({bid:10,ask:12}),11);
});

for(const [interval,ms] of [['1min',60000],['5min',300000],['15min',900000],['1hour',3600000]]){
  test(`fills use their containing ${interval} candle, including the last second`,()=>{
    const {context:c}=runtime(),points=[bar(0,100),bar(ms,101),bar(ms*3,103)];
    assert.equal(c.chartTradeIndex(points,{timestamp:new Date(ms-1000).toISOString()},interval),0);
    assert.equal(c.chartTradeIndex(points,{timestamp:new Date(ms).toISOString()},interval),1);
    assert.equal(c.chartTradeIndex(points,{timestamp:new Date(ms*2+1000).toISOString()},interval),-1);
    assert.equal(c.chartTradeIndex(points,{timestamp:'invalid'},interval),-1);
  });
}

test('sparse history keeps MA200 unavailable instead of drawing a partial average',()=>{
  const {context:c}=runtime();
  assert.ok(c.chartAverages([bar(0,10),bar(60000,10),bar(120000,10)],200).every(x=>x===null));
  assert.equal(c.mergeChartPoints([],[{timestamp:'invalid',mid:100}]).length,0);
});

test('starting and running lock every start-time input, even before instrument restoration',()=>{
  const {context:c,$,state,nodes}=runtime();
  const ids=['mode','autopilot','auto-style','paper-size','paper-balance','jev-every','profile','returns','s-dir','fifty-target-jpy'];
  ids.forEach($);
  state.pendingSession='start';c.syncSessionControls({running:false},true);
  ids.forEach(id=>assert.equal($(id).disabled,true,id));
  assert.equal($('start').textContent,'開始中…');
  state.pendingSession=null;c.syncSessionControls({running:true},false);
  ids.forEach(id=>assert.equal($(id).disabled,true,id));
  c.syncSessionControls({running:false},true);
  ids.forEach(id=>assert.equal($(id).disabled,false,id));
  $('autopilot').checked=true;c.syncSessionControls({running:false},true);
  assert.equal($('with-jev').disabled,true);
});

test('reload restores the running BTC paper settings, including zero-valued settings',()=>{
  const {context:c,$,state}=runtime();
  const snapshot={running:true,status:'running',started_at:'2026-09-20T00:00:00Z',instrument_id:'BTC',profile_name:'custom / UI',with_jev:true,signal_policy_name:'policy / UI',session_config:{profile:{quote:true},signal_policy:{min_direction_probability:.75},jev_every_seconds:2},paper:{autopilot_enabled:true,strategy_enabled:false,config:{autopilot_style:'fifty',size:.002,initial_balance:200000,autopilot_fifty_target_jpy:700,autopilot_fifty_target_units:7,autopilot_fifty_reentry_seconds:90,cooldown_seconds:0,slippage_units:0,autopilot_max_spread:0,deterministic_supervisor_enabled:false}}};
  assert.equal(c.restoreSession(snapshot),true);
  assert.equal($('instrument').value,'BTC');assert.equal($('mode').value,'paper');
  assert.equal($('paper-size').value,.002);assert.equal($('paper-balance').value,200000);
  assert.equal($('auto-style').value,'fifty');assert.equal($('fifty-target-jpy').value,700);
  assert.equal($('fifty-reentry-seconds').value,90);
  assert.equal($('p-cool').value,0);assert.equal($('paper-max-spread').value,0);
  assert.equal($('jev-every').value,2);
  assert.equal(state.restoredSignal.min_direction_probability,.75);
  assert.equal(c.restoreSession(snapshot),false);
});

test('reload restores observation mode and ignores stale settings during start preparation',()=>{
  const {context:c,$,state}=runtime();
  const snapshot={running:true,status:'stopped',started_at:'old-run',instrument_id:'BTC',with_jev:false,paper:null};
  assert.equal(c.restoreSession(snapshot),false);assert.equal($('instrument').value,'USD_JPY');
  snapshot.status='running';snapshot.started_at='new-run';
  c.restoreSession(snapshot);
  assert.equal($('instrument').value,'BTC');assert.equal($('mode').value,'observe');assert.equal($('with-jev').checked,false);
});


test('current fill list is newest first for either backend ordering and escapes text',()=>{
  const {context:c,$}=runtime();
  const old={timestamp:'2026-09-20T10:00:00Z',action:'OPEN',side:'LONG',size:1,price:100,reason:'<script>bad</script>'};
  const recent={...old,timestamp:'2026-09-20T11:00:00Z',action:'CLOSE',pnl:5};
  for(const rows of [[old,recent],[recent,old]]){
    c.renderExecutions('auto-live-executions',rows);
    const markup=$('auto-live-executions').innerHTML;
    assert.ok(markup.indexOf(recent.timestamp)<markup.indexOf(old.timestamp));
    assert.ok(markup.includes('&lt;script&gt;bad&lt;/script&gt;'));
  }
});


test('stopped preview quote shows spread and warns above configured ceiling',()=>{
  const {context:c,$}=runtime();
  $('mode').value='paper';$('autopilot').checked=true;$('paper-max-spread').value='1.5';
  c.renderTopQuote({bid:157.000,ask:157.099,spread_units:9.9,move_unit_label:'pips',display_symbol:'USD/JPY'},true);
  assert.ok($('spread').textContent.includes('spread 9.9 pips · preview'));
  assert.equal($('spread').className,'top-spread warn');
  assert.ok($('spread').title.includes('保存・売買判断には使いません'));
  c.renderTopQuote({bid:157.000,ask:157.010,spread_units:1.0,move_unit_label:'pips',display_symbol:'USD/JPY'},true);
  assert.equal($('spread').className,'top-spread');
});
