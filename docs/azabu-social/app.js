const C = window.AZABU_CARDS || [];
const V = window.AZABU_VISUALS || {};
const KEY = 'azabuSocialMaster30_v4';
const initialWeakTerms = new Set(['北前船','ホルムズ海峡','品種改良','殖産興業','富岡製糸場','石油危機','北極海航路','再生可能エネルギー','加工貿易','太平洋ベルト','IC工場','社会保障','地方交付税交付金','地方分権','議院内閣制','内閣不信任決議','違憲審査権','裁判官の独立','三審制','一票の格差']);
let S = loadState();
let session = [], ix = 0, score = 0, possible = 0, locked = false, mode = '';

function today(){ return new Date().toISOString().slice(0,10); }
function daysBetween(a,b){ return Math.floor((new Date(b)-new Date(a))/86400000); }
function freshState(){ return {version:4,start:today(),streak:0,lastDay:null,concept:{},variant:{},days:{},mistakes:[],active:null}; }
function loadState(){ try{ return Object.assign(freshState(), JSON.parse(localStorage.getItem(KEY)||'{}')); }catch(e){ return freshState(); } }
function saveState(){ localStorage.setItem(KEY, JSON.stringify(S)); updateDashboard(); }
function dayNo(){ return Math.max(1, Math.min(30, daysBetween(S.start,today())+1)); }
function shuffle(a){ return [...a].sort(()=>Math.random()-.5); }
function unique(a){ return [...new Set(a)]; }
function sample(a,n){ return shuffle(a).slice(0,n); }
function esc(s){ return String(s??'').replace(/[&<>\"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[m]||m)); }
function enc(s){ return encodeURIComponent(String(s)); }
function cls(d){ return d==='歴史'?'hist':d==='地理'?'geo':'civ'; }
function typeLabel(t){ return ({term:'用語',definition:'意味',year:'年代',reasonChoice:'理由',link:'知識リンク',oral:'口頭説明',timeline:'時代・年代',prefMap:'都道府県地図',symbol:'地図記号',graph:'グラフ読解',recall:'白紙想起'})[t]||t; }

function conceptState(c){
  if(!S.concept[c.id]) S.concept[c.id]={a:0,s:0,box:0,due:today(),last:null};
  return S.concept[c.id];
}
function variantState(k){ if(!S.variant[k]) S.variant[k]={a:0,s:0}; return S.variant[k]; }
function mastery(c){
  const x=conceptState(c); if(!x.a) return 0;
  return Math.min(4, Math.floor((x.s/x.a)*2)+Math.min(2,Math.floor((x.box||0)/2)));
}
function weakness(c){
  const x=conceptState(c), unseen=x.a===0?2.2:0, due=x.due<=today()?1.6:0, acc=x.a?x.s/x.a:.45;
  const init=[...initialWeakTerms].some(t=>c.term && c.term.includes(t))?1.7:0;
  return (1-acc)*4+(4-mastery(c))+unseen+due+init+Math.max(0,(c.priority||1)-1);
}
function samePool(c){ const p=C.filter(x=>x.domain===c.domain&&x.id!==c.id); const u=p.filter(x=>x.unit===c.unit); return u.length>=4?u:p; }
function distractTerms(c){ return unique(sample(samePool(c),10).map(x=>x.term)).slice(0,3); }
function distractDefs(c){ return unique(sample(samePool(c),10).map(x=>x.definition)).slice(0,3); }
function distractReasons(c){ return unique(sample(samePool(c).filter(x=>x.reason),12).map(x=>x.reason)).slice(0,3); }
function yearOpts(c){
  const y=Number(c.year); const pool=C.filter(x=>x.domain==='歴史'&&x.year&&x.id!==c.id).map(x=>Number(x.year));
  const close=pool.sort((a,b)=>Math.abs(a-y)-Math.abs(b-y)).slice(0,9); return unique(shuffle([y,...sample(close,3)])).slice(0,4).map(String);
}
function coreVariants(c){
  const out=[];
  out.push({key:c.id+'-term',card:c,type:'term',prompt:c.definition+'。この語句は？',answer:c.term,options:[c.term,...distractTerms(c)]});
  out.push({key:c.id+'-def',card:c,type:'definition',prompt:'「'+c.term+'」の説明として最も適切なものは？',answer:c.definition,options:[c.definition,...distractDefs(c)]});
  out.push({key:c.id+'-recall',card:c,type:'recall',prompt:c.definition+'。選択肢を見ずに、語句を口頭で答えてください。',answer:c.term,points:[c.term]});
  if(c.year) out.push({key:c.id+'-year',card:c,type:'year',prompt:'「'+c.term+'」に最も関係する年は？',answer:String(c.year),options:yearOpts(c)});
  if(c.reason){
    out.push({key:c.id+'-reason',card:c,type:'reasonChoice',prompt:'「'+c.term+'」の背景・理由として最も適切なものは？',answer:c.reason,options:[c.reason,...distractReasons(c)]});
    out.push({key:c.id+'-oral',card:c,type:'oral',prompt:'「'+c.term+'」について、なぜそうした制度・現象・出来事が生じたのか、口頭で説明してください。',points:reasonPoints(c),model:c.reason});
  }
  if(c.links&&c.links.length){
    const ans=c.links[Math.floor(Math.random()*c.links.length)];
    const other=C.filter(x=>x.domain===c.domain&&x.id!==c.id).flatMap(x=>x.links||[]).filter(x=>x!==ans&&!c.links.includes(x));
    out.push({key:c.id+'-link-'+ans,card:c,type:'link',prompt:'「'+c.term+'」と最も直接つながる語句は？',answer:ans,options:[ans,...unique(sample(other,10)).slice(0,3)]});
  }
  return out;
}
function reasonPoints(c){
  let pts=(c.reason||'').split(/[、。]/).map(x=>x.trim()).filter(x=>x.length>4).slice(0,3);
  if(c.links?.length) pts.push('関連語：'+c.links.slice(0,3).join('・'));
  return pts.length?pts:[c.reason||c.definition];
}

function prefNameFromCard(c){
  if(c.domain!=='地理'||c.unit!=='47都道府県') return null;
  const hit=(c.term||'').match(/^(.+?[都道府県])：/); return hit?hit[1]:null;
}
function prefVisuals(){
  const names=(V.prefectures||[]).map(x=>x[0]);
  return C.map(c=>{
    const name=prefNameFromCard(c); if(!name||!names.includes(name)) return null;
    const regionPool=names.filter(n=>n!==name);
    return {key:c.id+'-prefmap',card:c,type:'prefMap',prompt:'オレンジで示した都道府県はどこですか。',answer:name,options:[name,...sample(regionPool,3)],prefecture:name};
  }).filter(Boolean);
}
function symbolVisuals(){
  return (V.mapSymbols||[]).map(s=>({key:s.id,card:{id:s.id,domain:'地理',unit:'地図・地形図',term:s.name,definition:s.note,priority:2},type:'symbol',prompt:'この地図記号が表すものは？',answer:s.name,options:s.options,symbol:s.symbol,note:s.note}));
}
function graphVisuals(){
  return (V.graphs||[]).map(g=>({key:g.id,card:{id:g.id,domain:g.id==='g-fiscal'?'公民':'地理',unit:g.id==='g-fiscal'?'財政':'資料・グラフ',term:g.title,definition:g.explanation,priority:2},type:'graph',prompt:g.prompt,answer:g.answer,options:g.options,graph:g,explanation:g.explanation}));
}
function oralVisuals(){
  return (V.oralVisuals||[]).map(o=>({key:o.id,card:{id:o.id,domain:o.domain,unit:o.unit,term:o.prompt,definition:o.model,priority:3},type:'oral',prompt:o.prompt,points:o.points,model:o.model}));
}
function timelineQuestion(){
  const pool=C.filter(c=>c.domain==='歴史'&&c.year);
  const chosen=sample(pool,1)[0]; if(!chosen) return null;
  const era=eraFromYear(Number(chosen.year));
  return {key:'timeline-'+chosen.id+'-'+Math.random().toString(36).slice(2,7),card:chosen,type:'timeline',prompt:'この出来事は主にどの時代のことですか。',answer:era?.name||'不明',options:timelineEraOptions(era?.name),timelineYear:Number(chosen.year),timelineEra:era?.name};
}
function timelineEraOptions(answer){
  const eras=(V.eras||[]).map(x=>x.name); const idx=eras.indexOf(answer); const near=eras.filter((_,i)=>i!==idx&&Math.abs(i-idx)<=3); return shuffle([answer,...sample(near.length>=3?near:eras.filter(x=>x!==answer),3)]);
}
function allCore(){ return C.flatMap(coreVariants); }
function allVisual(){ return [...prefVisuals(),...symbolVisuals(),...graphVisuals()]; }
function allQuestions(){ return [...allCore(),...allVisual(),...oralVisuals()]; }

function questionWeak(q){
  const c=q.card; const base=(C.find(x=>x.id===c.id)?weakness(c):visualWeak(q.key)); const vs=variantState(q.key); return base+(vs.a===0?1.0:0);
}
function visualWeak(key){ const v=variantState(key); if(!v.a) return 5.2; return (1-v.s/v.a)*4+1; }
function chooseFrom(arr,n){
  const ranked=arr.slice().sort((a,b)=>questionWeak(b)-questionWeak(a)+(Math.random()-.5)*1.1); const out=[];
  for(const q of ranked){ if(out.length>=n) break; if(!out.some(x=>x.key===q.key)) out.push(q); }
  return shuffle(out).slice(0,n);
}
function chooseSession(m){
  const all=allQuestions();
  if(m==='visual') return chooseFrom(allVisual(),10);
  if(m==='oral') return chooseFrom(all.filter(q=>q.type==='oral'||q.type==='recall'),8);
  if(m==='timeline') return Array.from({length:8},()=>timelineQuestion()).filter(Boolean);
  if(m==='link') return chooseFrom(all.filter(q=>q.type==='link'||q.type==='reasonChoice'||q.type==='graph'),10);
  if(['歴史','地理','公民'].includes(m)){
    let pool=all.filter(q=>q.card.domain===m);
    if(m==='地理') pool=[...pool,...allVisual().filter(q=>q.card.domain==='地理')];
    if(m==='公民') pool=[...pool,...allVisual().filter(q=>q.card.domain==='公民')];
    return chooseFrom(pool,12);
  }
  if(m==='weak') return chooseFrom(all,10);
  if(m==='daily'){
    const picked=[]; const add=(arr,n)=>{for(const q of chooseFrom(arr,n*3)){if(picked.length>=20||n<=0)break;if(!picked.some(x=>x.key===q.key)){picked.push(q);n--;}}};
    const due=all.filter(q=>{const c=C.find(x=>x.id===q.card.id); return c&&conceptState(c).due<=today();});
    const unseen=all.filter(q=>variantState(q.key).a===0);
    add(due,7); add(unseen.filter(q=>!['oral','recall','graph','prefMap','symbol'].includes(q.type)),4); add(allVisual(),4); add(all.filter(q=>q.type==='oral'||q.type==='recall'),3);
    for(let i=0;i<2;i++){const tq=timelineQuestion();if(tq)picked.push(tq);}
    add(all,20-picked.length); return shuffle(picked).slice(0,20);
  }
  return chooseFrom(all,10);
}

function startSession(m){
  if(S.active && !confirm('途中保存中のセッションがあります。終了して新しいセッションを始めますか？')) return;
  mode=m; session=chooseSession(m); ix=0; score=0; possible=0; locked=false;
  S.active={mode,session,index:0,score:0,possible:0,started:Date.now()}; saveState(); openQuiz(); renderQuestion();
}
function openQuiz(){
  ['home','weakpage','note','data'].forEach(id=>document.getElementById(id).classList.add('hidden'));
  document.getElementById('quiz').classList.remove('hidden'); document.querySelector('.tabshell').classList.add('hidden'); window.scrollTo(0,0);
}
function pauseSession(){
  if(!S.active){showPage('home',document.querySelector('[data-p="home"]'));return;}
  S.active.index=ix; S.active.score=score; S.active.possible=possible; saveState();
  document.getElementById('quiz').classList.add('hidden'); document.querySelector('.tabshell').classList.remove('hidden'); showPage('home',document.querySelector('[data-p="home"]'));
}
function resumeSession(){
  if(!S.active) return;
  mode=S.active.mode; session=S.active.session||[]; ix=Math.min(S.active.index||0,Math.max(0,session.length-1)); score=S.active.score||0; possible=S.active.possible||0; locked=false;
  openQuiz(); renderQuestion();
}
function discardSession(){ if(!S.active)return; if(confirm('途中のセッションを終了しますか？学習済みの回答記録は残ります。')){S.active=null;saveState();updateResumeCard();} }

function renderQuestion(){
  locked=false; const q=session[ix]; if(!q){finishSession();return;}
  document.getElementById('qnum').textContent=(ix+1)+' / '+session.length;
  document.getElementById('pbar').style.width=((ix/session.length)*100)+'%'; document.getElementById('modeName').textContent=modeLabel(mode);
  document.getElementById('meta').innerHTML=`<span class="pill ${cls(q.card.domain)}">${q.card.domain}</span><span class="pill">${esc(q.card.unit||'')}</span><span class="pill type">${typeLabel(q.type)}</span>`;
  document.getElementById('prompt').textContent=q.prompt; document.getElementById('feedback').className='hidden'; document.getElementById('feedback').innerHTML=''; document.getElementById('nextBtn').classList.add('hidden');
  renderContext(q); renderAnswer(q);
}
function modeLabel(m){ return ({daily:'今日の20問',weak:'弱点レスキュー',visual:'地図・グラフ',oral:'口頭説明',timeline:'歴史の位置づけ',link:'知識リンク'})[m]||m; }
function renderContext(q){
  const el=document.getElementById('contextVisual'); el.innerHTML='';
  if(q.type==='prefMap') el.innerHTML=renderPrefMap(q.prefecture,false);
  else if(q.type==='symbol') el.innerHTML=renderSymbol(q.symbol);
  else if(q.type==='graph') el.innerHTML=renderGraph(q.graph);
  else if(q.card.domain==='歴史') el.innerHTML=renderHistoryTrack(q.card,false);
  else if(q.card.domain==='公民') el.innerHTML=renderCivicsTrack(q.card);
  else if(q.card.domain==='地理') el.innerHTML=renderGeoTrack(q.card);
}
function renderAnswer(q){
  const a=document.getElementById('answerArea');
  if(['term','definition','year','reasonChoice','link','prefMap','symbol','graph','timeline'].includes(q.type)){
    a.innerHTML='<div class="options">'+shuffle(q.options).map((x,i)=>`<button class="option" data-v="${enc(x)}" onclick="pickOption(this)">${String.fromCharCode(65+i)}. ${esc(x)}</button>`).join('')+'</div>';
  }else if(q.type==='oral'||q.type==='recall'){
    a.innerHTML=`<div class="oralReady"><strong>まず、答えを口頭で言う</strong><div class="small">iPadへの文字入力は不要です。言い終わったら確認してください。</div><button class="btn" style="margin-top:12px" onclick="revealOral()">答えに入るべき内容を見る</button></div>`;
  }
}
function pickOption(btn){
  if(locked)return; const q=session[ix], val=decodeURIComponent(btn.dataset.v), ok=val===String(q.answer);
  document.querySelectorAll('.option').forEach(b=>{b.disabled=true;if(b.dataset.v&&decodeURIComponent(b.dataset.v)===String(q.answer))b.classList.add('correct');}); if(!ok)btn.classList.add('wrong');
  record(q,ok?1:0,1); showChoiceFeedback(q,ok);
}
function showChoiceFeedback(q,ok){
  const f=document.getElementById('feedback'); f.className='feedback';
  let html=`<div class="answerTitle">${ok?'✓ 正解':'答え：'+esc(q.answer)}</div>`;
  if(q.type==='prefMap') html+=renderPrefMap(q.prefecture,true)+`<div class="link"><b>${esc(q.card.term)}</b><br>${esc(q.card.definition||'')}</div>`;
  else if(q.type==='symbol') html+=`<div class="link"><b>確認：</b> ${esc(q.note||q.card.definition||'')}</div>`;
  else if(q.type==='graph') html+=`<div class="link"><b>読み取り：</b> ${esc(q.explanation||'')}</div>`;
  else { html+=`<div style="margin-top:8px"><b>${esc(q.card.term)}</b>：${esc(q.card.definition||'')}</div>`; if(q.card.reason)html+=`<div class="link"><b>なぜ？</b> ${esc(q.card.reason)}</div>`; if(q.card.links?.length)html+=`<div class="link"><b>つなぐ：</b> ${q.card.links.map(esc).join(' → ')}</div>`; }
  if(q.card.domain==='歴史') html+=renderHistoryTrack(q.card,true);
  f.innerHTML=html; document.getElementById('nextBtn').classList.remove('hidden');
}
function revealOral(){
  if(locked)return; const q=session[ix], f=document.getElementById('feedback'); f.className='feedback';
  const pts=q.points?.length?q.points:reasonPoints(q.card);
  f.innerHTML=`<div class="answerTitle">答えに入っていればよい要素</div><ul class="pointList">${pts.map(p=>`<li>${esc(p)}</li>`).join('')}</ul><div class="link"><b>解答の核：</b> ${esc(q.model||q.card.reason||q.card.definition||q.answer||'')}</div>${q.card.domain==='歴史'?renderHistoryTrack(q.card,true):''}<div class="score3"><button class="s0" onclick="gradeOral(0)">言えなかった</button><button class="s1" onclick="gradeOral(1)">一部は言えた</button><button class="s2" onclick="gradeOral(2)">ほぼ言えた</button></div>`;
}
function gradeOral(n){ if(locked)return; const q=session[ix]; record(q,n,2); const sc=document.querySelector('.score3'); if(sc)sc.innerHTML='<b>記録しました。次回の出題頻度に反映します。</b>'; document.getElementById('nextBtn').classList.remove('hidden'); }

function record(q,sc,max){
  if(locked)return; locked=true; const c=C.find(x=>x.id===q.card.id); const v=variantState(q.key); v.a++; v.s+=sc/max;
  if(c){ const x=conceptState(c); x.a++;x.s+=sc/max;x.last=today(); if(sc===max)x.box=Math.min(5,(x.box||0)+1);else if(sc>0)x.box=Math.max(1,x.box||0);else x.box=0; const gap=sc===max?[0,1,3,7,14,30][x.box]:(sc>0?2:0); const d=new Date();d.setDate(d.getDate()+gap);x.due=d.toISOString().slice(0,10); }
  if(sc<max){S.mistakes.unshift({date:today(),key:q.key,term:q.card.term,domain:q.card.domain,unit:q.card.unit,type:q.type,score:sc,max});S.mistakes=S.mistakes.slice(0,180);}
  const td=S.days[today()]||{n:0,s:0,m:0};td.n++;td.s+=sc;td.m+=max;S.days[today()]=td; score+=sc;possible+=max;
  if(S.lastDay!==today()){if(S.lastDay&&daysBetween(S.lastDay,today())===1)S.streak=(S.streak||0)+1;else S.streak=1;S.lastDay=today();}
  if(S.active){S.active.index=ix+1;S.active.score=score;S.active.possible=possible;}
  saveState();
}
function nextQuestion(){
  if(S.active && S.active.index>ix) ix=S.active.index; else ix++;
  if(ix>=session.length){finishSession();return;} locked=false; renderQuestion(); window.scrollTo({top:0,behavior:'smooth'});
}
function finishSession(){
  document.getElementById('quiz').classList.add('hidden');document.querySelector('.tabshell').classList.remove('hidden');const pct=possible?Math.round(score/possible*100):0; const weak=topWeak(5); S.active=null;saveState();
  document.getElementById('doneBody').innerHTML=`<p>今回の達成度 <span class="kpi">${pct}%</span></p><p>次に優先する知識：</p><ol>${weak.map(c=>`<li>${esc(c.domain)} / ${esc(c.unit)} / ${esc(c.term)}</li>`).join('')}</ol><p class="small">誤答・部分点は早めに、定着した知識は間隔を空けて再登場します。</p>`;document.getElementById('doneModal').classList.remove('hidden');
}
function closeDone(){document.getElementById('doneModal').classList.add('hidden');showPage('home',document.querySelector('[data-p="home"]'));}
function speakQuestion(){if(!('speechSynthesis'in window)||!session[ix])return;speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(session[ix].prompt);u.lang='ja-JP';u.rate=.95;speechSynthesis.speak(u);}

function eraFromYear(y){ return (V.eras||[]).find(e=>y>=e.from&&y<e.to) || null; }
function inferEra(card){
  if(card.year) return eraFromYear(Number(card.year)); const s=(card.unit||'')+' '+(card.term||'')+' '+(card.definition||'');
  const names=(V.eras||[]).map(e=>e.name); for(const n of names){if(s.includes(n))return (V.eras||[]).find(e=>e.name===n);} 
  const map=[['聖徳|遣隋|大化','飛鳥'],['律令|聖武|天平','奈良'],['藤原|摂関|国風|平清盛','平安'],['頼朝|御家人|元寇|北条','鎌倉'],['足利|勘合|応仁|惣村','室町'],['信長|秀吉|刀狩|太閤','安土桃山'],['徳川|参勤|鎖国|元禄|享保|寛政|天保|田沼|北前船','江戸'],['明治|殖産|自由民権|日清|日露|地租','明治'],['大正|普通選挙','大正'],['満州|太平洋戦争|GHQ|高度経済|オイル','昭和']];
  for(const [re,n] of map){if(new RegExp(re).test(s))return (V.eras||[]).find(e=>e.name===n);} return null;
}
function renderHistoryTrack(card,reveal){
  const era=inferEra(card); if(!era)return '';
  const segs=(V.eras||[]).map(e=>`<div class="trackSeg ${e.name===era.name?'active':''}">${e.name}</div>`).join('');
  const exact=reveal&&card.year?`<div class="eraExact">この出来事：<b>${esc(card.year)}年ごろ</b></div>`:'';
  return `<div class="timelineQuestion"><div class="eraRange">全歴史の中では「${esc(era.name)}時代」</div><div class="track">${segs}</div><div class="trackNote">左＝古い　→　右＝新しい</div>${exact}</div>`;
}
function renderCivicsTrack(card){
  const u=card.unit||''; const track=V.civicsTrack||[]; let active=track.find(x=>u.includes(x)); if(!active&&u==='内閣')active='内閣'; if(!active&&u.includes('裁判'))active='裁判所';
  return `<div class="timelineQuestion"><div class="eraRange">公民の全体像：今は「${esc(active||u||'横断')}」</div><div class="track">${track.map(x=>`<div class="trackSeg ${x===active?'active':''}">${x}</div>`).join('')}</div></div>`;
}
function renderGeoTrack(card){
  const u=card.unit||'';const track=V.geoTrack||[];let active=track.find(x=>u.includes(x));
  return `<div class="timelineQuestion"><div class="eraRange">地理の全体像：今は「${esc(active||u||'横断')}」</div><div class="track">${track.map(x=>`<div class="trackSeg ${x===active?'active':''}">${x}</div>`).join('')}</div></div>`;
}
function renderPrefMap(target,reveal){
  const prefs=V.prefectures||[]; const scaleX=47,scaleY=34; const tiles=prefs.map(([n,x,y])=>`<div class="prefTile ${n===target?'target':''} ${reveal&&n===target?'revealed':''}" style="left:${x*scaleX+18}px;top:${y*scaleY+12}px">${reveal&&n===target?esc(n):''}</div>`).join('');
  return `<div class="tileMapWrap"><div class="tileMap"><div class="mapNorth">N</div>${tiles}</div><div class="visualCaption">都道府県の相対位置を覚えるための学習用タイル地図</div></div>`;
}
function renderSymbol(k){
  let body=''; if(k==='post')body='<div class="symbolText">〒</div>'; else if(k==='school')body='<div class="symbolText">文</div>'; else if(k==='temple')body='<div class="symbolText">卍</div>'; else if(k==='shrine')body='<svg class="symbolSvg" viewBox="0 0 120 120"><g stroke="#111" stroke-width="8" fill="none" stroke-linecap="square"><path d="M22 32H98M32 22H88M42 33V96M78 33V96M34 60H86"/></g></svg>'; else if(k==='police')body='<svg class="symbolSvg" viewBox="0 0 120 120"><g stroke="#111" stroke-width="8" stroke-linecap="round"><path d="M32 26L88 94M88 26L32 94"/><path d="M24 18L40 34M96 18L80 34"/></g></svg>'; else body='<svg class="symbolSvg" viewBox="0 0 120 120"><path d="M60 18L102 94H18Z" fill="none" stroke="#111" stroke-width="7"/><circle cx="60" cy="65" r="7" fill="#111"/></svg>';
  return `<div class="symbolCard">${body}</div><div class="visualCaption">国土地理院の地図記号をもとにした学習表示</div>`;
}
function renderGraph(g){
  if(!g)return''; const W=720,H=250,pad={l:48,r:18,t:18,b:46};const max=Math.max(...g.series.flatMap(s=>s.values),100);let svg=`<svg class="chartSvg" viewBox="0 0 ${W} ${H}" role="img">`;
  for(let i=0;i<=4;i++){const y=pad.t+(H-pad.t-pad.b)*i/4;svg+=`<line x1="${pad.l}" y1="${y}" x2="${W-pad.r}" y2="${y}" stroke="#e2e8ee"/><text x="${pad.l-8}" y="${y+4}" font-size="10" text-anchor="end" fill="#6b7885">${Math.round(max*(4-i)/4)}</text>`;}
  if(g.kind==='line'){
    const innerW=W-pad.l-pad.r,innerH=H-pad.t-pad.b; g.series.forEach((s,si)=>{const pts=s.values.map((v,i)=>`${pad.l+innerW*i/(s.values.length-1)},${pad.t+innerH*(1-v/max)}`).join(' ');svg+=`<polyline points="${pts}" fill="none" stroke="${si===0?'#245f9e':'#d4772c'}" stroke-width="4"/>`;s.values.forEach((v,i)=>{const x=pad.l+innerW*i/(s.values.length-1),y=pad.t+innerH*(1-v/max);svg+=`<circle cx="${x}" cy="${y}" r="3.5" fill="${si===0?'#245f9e':'#d4772c'}"/>`;});});
    g.labels.forEach((lab,i)=>{if(i%Math.ceil(g.labels.length/6)===0||i===g.labels.length-1){const x=pad.l+(W-pad.l-pad.r)*i/(g.labels.length-1);svg+=`<text x="${x}" y="${H-18}" font-size="10" text-anchor="middle" fill="#667788">${esc(lab)}</text>`;}});
  }else{
    const groups=g.series.length,bands=g.labels.length,innerW=W-pad.l-pad.r; if(g.kind==='stacked'){
      const bw=innerW/(groups*1.8);g.series.forEach((s,si)=>{let acc=0;const x=pad.l+innerW*(si+.5)/groups-bw/2;s.values.forEach((v,j)=>{const h=(H-pad.t-pad.b)*(v/100),base=H-pad.b-(H-pad.t-pad.b)*(acc/100)-h;svg+=`<rect x="${x}" y="${base}" width="${bw}" height="${h}" rx="3" fill="${['#245f9e','#d4772c','#5c9b65'][j%3]}"/>`;acc+=v;});svg+=`<text x="${x+bw/2}" y="${H-18}" font-size="11" text-anchor="middle" fill="#667788">${esc(s.name)}</text>`;});
    }else{
      const bw=innerW/(bands*1.8);g.labels.forEach((lab,i)=>{const v=g.series[0].values[i],h=(H-pad.t-pad.b)*(v/max),x=pad.l+innerW*(i+.5)/bands-bw/2,y=H-pad.b-h;svg+=`<rect x="${x}" y="${y}" width="${bw}" height="${h}" rx="4" fill="#245f9e"/><text x="${x+bw/2}" y="${H-18}" font-size="10" text-anchor="middle" fill="#667788">${esc(lab)}</text>`;});
    }
  }
  svg+='</svg>'; const legend=g.series.length>1?`<div class="legend">${g.series.map(s=>`<span>${esc(s.name)}</span>`).join('')}</div>`:''; return `<div class="chartWrap"><div class="chartTitle">${esc(g.title)}</div>${svg}${legend}<div class="chartNote">読解練習用の模式データ</div></div>`;
}

function topWeak(n){ return C.slice().sort((a,b)=>weakness(b)-weakness(a)).slice(0,n); }
function unitStats(domain){
  const units=unique(C.filter(c=>c.domain===domain).map(c=>c.unit)); return units.map(u=>{const cs=C.filter(c=>c.domain===domain&&c.unit===u),vals=cs.map(mastery);return {u,score:vals.reduce((a,b)=>a+b,0)/(4*vals.length),seen:cs.filter(c=>conceptState(c).a>0).length,total:cs.length};});
}
function renderWeak(){
  for(const [d,id] of [['歴史','mapH'],['地理','mapG'],['公民','mapC']])document.getElementById(id).innerHTML=unitStats(d).map(x=>`<div class="unit"><div class="unithead"><span>${esc(x.u)}</span><span class="small">${x.seen}/${x.total}</span></div><div class="bar"><div style="width:${Math.round(x.score*100)}%"></div></div></div>`).join('');
  document.getElementById('weakList').innerHTML=topWeak(15).map((c,i)=>`<div class="weakitem"><span><b>${i+1}. ${esc(c.term)}</b><br><span class="small">${c.domain} / ${esc(c.unit)}</span></span><span><span class="small">弱点 ${weakness(c).toFixed(1)}</span><br><button class="mini" onclick="relearnOne('${c.id}')">↻ 再学習</button></span></div>`).join('');
}
function renderNotes(){
  const e=document.getElementById('mistakes'); e.innerHTML=S.mistakes.length?S.mistakes.slice(0,60).map(m=>`<details><summary>${m.date}｜${m.domain}｜${esc(m.term)}</summary><p>${esc(m.unit)} / ${typeLabel(m.type)} / ${m.score}/${m.max}</p></details>`).join(''):'<p class="small">まだ間違いはありません。</p>';
}
function relearnOne(id){ const c=C.find(x=>x.id===id);if(!c)return;S.concept[id]={a:0,s:0,box:0,due:today(),last:null};Object.keys(S.variant).filter(k=>k.startsWith(id+'-')).forEach(k=>delete S.variant[k]);saveState();renderWeak(); }
function retestMastered(){const cs=C.filter(c=>mastery(c)>=3);if(!cs.length){alert('定着判定の知識はまだありません。');return;}if(!confirm(cs.length+'件を今日の復習対象へ戻しますか？過去成績は残ります。'))return;cs.forEach(c=>{const x=conceptState(c);x.box=0;x.due=today();});saveState();alert('再テスト対象に戻しました。');}

function showPage(p,b){
  ['home','quiz','weakpage','note','data'].forEach(id=>document.getElementById(id).classList.add('hidden'));document.getElementById(p).classList.remove('hidden');document.querySelector('.tabshell').classList.remove('hidden');document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));if(b)b.classList.add('active');if(p==='weakpage')renderWeak();if(p==='note')renderNotes();updateDashboard();window.scrollTo(0,0);
}
function updateDashboard(){
  document.getElementById('dayBadge').textContent='Day '+dayNo()+' / 30';const td=S.days[today()]||{n:0};document.getElementById('todayCount').textContent=td.n||0;document.getElementById('covered').textContent=C.filter(c=>conceptState(c).a>0).length;document.getElementById('weakCount').textContent=C.filter(c=>conceptState(c).a>0&&mastery(c)<2).length;const vals=Object.values(S.variant),a=vals.reduce((s,x)=>s+x.a,0),sc=vals.reduce((s,x)=>s+x.s,0);document.getElementById('acc').textContent=a?Math.round(sc/a*100)+'%':'—';document.getElementById('coreCount').textContent=C.length;updateResumeCard();
}
function updateResumeCard(){const el=document.getElementById('resumeCard');if(!S.active||!S.active.session?.length){el.classList.add('hidden');return;}el.classList.remove('hidden');document.getElementById('resumeTitle').textContent=modeLabel(S.active.mode)+' の続き';document.getElementById('resumeText').textContent=`${Math.min((S.active.index||0)+1,S.active.session.length)}問目付近 / 全${S.active.session.length}問。ここから再開できます。`;}
function copyReport(){
  const tw=topWeak(20),dom=['歴史','地理','公民'].map(d=>{const cs=C.filter(c=>c.domain===d),seen=cs.filter(c=>conceptState(c).a>0),a=seen.reduce((s,c)=>s+conceptState(c).a,0),sc=seen.reduce((s,c)=>s+conceptState(c).s,0);return `${d}: 触れた知識 ${seen.length}/${cs.length}, 達成率 ${a?Math.round(sc/a*100):0}%`;}).join('\n');
  const txt=`麻布社会 MASTER 30 v4 弱点レポート\n日付: ${today()}\nDay ${dayNo()}/30\n${dom}\n\n優先弱点:\n${tw.map((c,i)=>`${i+1}. ${c.domain}/${c.unit}/${c.term} (弱点 ${weakness(c).toFixed(1)})`).join('\n')}\n\nこの弱点に合わせ、基礎知識→地図/グラフ→知識リンク→口頭説明の順で追加対策を作ってください。`;
  navigator.clipboard.writeText(txt).then(()=>alert('弱点レポートをコピーしました。'));
}
function exportState(){const b=new Blob([JSON.stringify(S,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='azabu_social_v4_'+today()+'.json';a.click();URL.revokeObjectURL(a.href);}
function importState(ev){const f=ev.target.files[0];if(!f)return;const r=new FileReader();r.onload=()=>{try{S=Object.assign(freshState(),JSON.parse(r.result));saveState();alert('進捗を読み込みました。');}catch(e){alert('読み込みに失敗しました。');}};r.readAsText(f);}
function resetAllData(){
  if(!confirm('回答履歴・弱点・途中セッションをすべて消します。\nお子さん用に0から開始する場合は「OK」を押してください。'))return;
  if(!confirm('本当に全学習データをリセットしますか？この操作は元に戻せません。'))return;
  localStorage.removeItem(KEY);S=freshState();session=[];ix=0;score=0;possible=0;saveState();alert('学習データをリセットしました。Day 1から開始します。');showPage('home',document.querySelector('[data-p="home"]'));
}

updateDashboard();
if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js').catch(()=>{}));}
