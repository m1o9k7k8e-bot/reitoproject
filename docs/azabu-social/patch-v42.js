// v4.2: timeline event visibility + real-map prefecture knowledge questions.
(function(){
  const MAP_URL='https://raw.githubusercontent.com/PA4KEV/japan-vector-map/main/japan-prefectures.svg';
  const MAP_CACHE='azabu-social-map-v1';
  let mapSeq=0;

  const prefLabels={
    '北海道':['hokkaido'], '青森県':['aomori'], '岩手県':['iwate'], '宮城県':['miyagi'], '秋田県':['akita'], '山形県':['yamagata'], '福島県':['fukushima'],
    '茨城県':['ibaraki'], '栃木県':['tochigi'], '群馬県':['gunma'], '埼玉県':['saitama'], '千葉県':['chiba'], '東京都':['tokyo'], '神奈川県':['kanagawa'],
    '新潟県':['nigata','niigata'], '富山県':['toyama'], '石川県':['ishikawa'], '福井県':['fukui'], '山梨県':['yamanashi'], '長野県':['nagano'], '岐阜県':['gifu'], '静岡県':['shizuoka'], '愛知県':['aichi'],
    '三重県':['mie'], '滋賀県':['shiga'], '京都府':['kyoto','kyouto'], '大阪府':['osaka','oosaka'], '兵庫県':['hyogo','hyougo'], '奈良県':['nara'], '和歌山県':['wakayama'],
    '鳥取県':['tottori'], '島根県':['shimane'], '岡山県':['okayama'], '広島県':['hiroshima'], '山口県':['yamaguchi'],
    '徳島県':['tokushima'], '香川県':['kagawa'], '愛媛県':['ehime'], '高知県':['kochi'],
    '福岡県':['fukuoka'], '佐賀県':['saga'], '長崎県':['nagasaki'], '熊本県':['kumamoto'], '大分県':['oita','ooita'], '宮崎県':['miyazaki'], '鹿児島県':['kagoshima'], '沖縄県':['okinawa']
  };
  const knownRoman=new Set(Object.values(prefLabels).flat());

  function injectStyles(){
    if(document.getElementById('v42styles'))return;
    const st=document.createElement('style');st.id='v42styles';st.textContent=`
      .eventFocus{border:2px solid #d8e5ef;background:#fff;border-radius:16px;padding:14px 16px;margin-bottom:12px}
      .eventFocus .eventLabel{font-size:12px;font-weight:850;color:#6a7885;letter-spacing:.04em}
      .eventFocus .eventName{font-size:22px;font-weight:900;line-height:1.35;margin-top:3px;color:#102f4c}
      .realMapWrap{border:1px solid #dbe5ec;border-radius:18px;padding:10px;background:#fbfdff;margin:8px 0 12px;overflow:hidden}
      .realMapStage{min-height:330px;display:flex;align-items:center;justify-content:center;position:relative}
      .realMapStage svg{width:100%;height:auto;max-height:430px;display:block}
      .mapLoading{color:#708090;font-size:13px;padding:120px 0}
      .realMapCaption{font-size:12px;color:#667788;text-align:center;margin-top:6px;line-height:1.5}
      .mapRevealName{display:inline-block;margin-top:6px;padding:5px 10px;border-radius:999px;background:#fff1d6;color:#7a4b00;font-weight:900}
      .mapSource{font-size:10px;color:#8a96a1;text-align:center;margin-top:4px}
      @media(max-width:720px){.realMapStage{min-height:285px}.eventFocus .eventName{font-size:20px}}
    `;document.head.appendChild(st);
  }
  injectStyles();

  timelineQuestion=function(){
    const pool=C.filter(c=>c.domain==='歴史'&&c.year);
    const chosen=sample(pool,1)[0]; if(!chosen)return null;
    const era=eraFromYear(Number(chosen.year));
    return {key:'timeline-'+chosen.id+'-'+Math.random().toString(36).slice(2,7),card:chosen,type:'timeline',
      prompt:'「'+chosen.term+'」は主にどの時代のことですか。',answer:era?.name||'不明',options:timelineEraOptions(era?.name),timelineYear:Number(chosen.year),timelineEra:era?.name};
  };

  const priorRenderContext=renderContext;
  renderContext=function(q){
    if(q.type==='timeline'){
      const segs=(V.eras||[]).map(e=>`<div class="trackSeg">${e.name}</div>`).join('');
      document.getElementById('contextVisual').innerHTML=`
        <div class="eventFocus"><div class="eventLabel">今回位置づける出来事</div><div class="eventName">${esc(q.card.term)}</div></div>
        <div class="timelineQuestion"><div class="eraRange">この出来事が全歴史のどこに入るか考える</div><div class="track">${segs}</div><div class="trackNote">左＝古い　→　右＝新しい</div></div>`;
      return;
    }
    priorRenderContext(q);
  };

  prefVisuals=function(){
    const pos=new Map((V.prefectures||[]).map(x=>[x[0],{x:x[1],y:x[2]}]));
    const pcs=C.map(c=>({c,name:prefNameFromCard(c)})).filter(x=>x.name&&pos.has(x.name));
    const out=[];
    for(const x of pcs){
      const p=pos.get(x.name);
      const near=pcs.filter(y=>y.name!==x.name).sort((a,b)=>{
        const pa=pos.get(a.name),pb=pos.get(b.name);
        const da=Math.hypot(pa.x-p.x,pa.y-p.y),db=Math.hypot(pb.x-p.x,pb.y-p.y);return da-db;
      });
      const d1=unique(near.slice(0,10).map(y=>y.c.definition).filter(Boolean));
      const opts1=unique([x.c.definition,...sample(d1,3)]);
      while(opts1.length<4){const more=pcs.filter(y=>y.name!==x.name).map(y=>y.c.definition).filter(Boolean);const z=sample(more,1)[0];if(z&&!opts1.includes(z))opts1.push(z);}
      out.push({key:x.c.id+'-prefknow',card:x.c,type:'prefMap',prefecture:x.name,
        prompt:'地図でオレンジ色に示した都道府県について、最も関係の深い説明を選びなさい。都道府県名は隠しています。',
        answer:x.c.definition,options:opts1.slice(0,4),mapMode:'knowledge'});
      if(x.c.reason){
        const d2=unique(near.slice(0,12).map(y=>y.c.reason).filter(Boolean));
        const opts2=unique([x.c.reason,...sample(d2,3)]);
        while(opts2.length<4){const more=pcs.filter(y=>y.name!==x.name).map(y=>y.c.reason).filter(Boolean);const z=sample(more,1)[0];if(z&&!opts2.includes(z))opts2.push(z);}
        out.push({key:x.c.id+'-prefreason',card:x.c,type:'prefMap',prefecture:x.name,
          prompt:'地図でオレンジ色に示した都道府県について、そこで見られる産業・農業・地域の特色の理由として最も適切なものを選びなさい。',
          answer:x.c.reason,options:opts2.slice(0,4),mapMode:'reason'});
      }
    }
    return out;
  };

  async function getMapText(){
    try{
      if('caches' in window){const hit=await caches.match(MAP_URL);if(hit)return await hit.text();}
      const r=await fetch(MAP_URL,{mode:'cors',cache:'force-cache'});if(!r.ok)throw new Error('map '+r.status);
      if('caches' in window){try{const c=await caches.open(MAP_CACHE);await c.put(MAP_URL,r.clone());}catch(e){}}
      return await r.text();
    }catch(e){return null;}
  }
  function findTargetGroup(doc,target){
    const candidates=prefLabels[target]||[];
    for(const g of doc.querySelectorAll('g')){
      const lab=(g.getAttributeNS('http://www.inkscape.org/namespaces/inkscape','label')||g.getAttribute('inkscape:label')||'').toLowerCase();
      if(candidates.includes(lab))return g;
    }
    return null;
  }
  function allPrefGroups(doc){
    const arr=[];
    for(const g of doc.querySelectorAll('g')){
      const lab=(g.getAttributeNS('http://www.inkscape.org/namespaces/inkscape','label')||g.getAttribute('inkscape:label')||'').toLowerCase();
      if(knownRoman.has(lab))arr.push(g);
    }
    return arr;
  }
  async function mountRealMap(id,target){
    const host=document.getElementById(id);if(!host)return;
    const txt=await getMapText();if(!host.isConnected)return;
    if(!txt){host.innerHTML='<div class="mapLoading">日本地図を読み込めませんでした。通信を確認して再読み込みしてください。</div>';return;}
    const doc=new DOMParser().parseFromString(txt,'image/svg+xml');
    const svg=doc.documentElement;svg.removeAttribute('width');svg.removeAttribute('height');svg.setAttribute('aria-label','日本の都道府県地図');
    const groups=allPrefGroups(doc);
    groups.forEach(g=>{g.style.display='inline';g.querySelectorAll('path,polygon').forEach(p=>{p.style.fill='#edf2f5';p.style.fillOpacity='1';p.style.stroke='#6f7c87';p.style.strokeWidth='1.15px';});});
    const tg=findTargetGroup(doc,target);
    if(tg){tg.style.display='inline';tg.querySelectorAll('path,polygon').forEach(p=>{p.style.fill='#f59e0b';p.style.fillOpacity='.9';p.style.stroke='#8a4f00';p.style.strokeWidth='2.5px';});}
    host.innerHTML='';host.appendChild(document.importNode(svg,true));
  }
  renderPrefMap=function(target,reveal){
    const id='realmap-'+(++mapSeq);
    setTimeout(()=>mountRealMap(id,target),0);
    return `<div class="realMapWrap"><div id="${id}" class="realMapStage"><div class="mapLoading">日本地図を読み込み中…</div></div>
      <div class="realMapCaption">${reveal?`オレンジ色：<span class="mapRevealName">${esc(target)}</span>`:'都道府県名は隠しています。オレンジ色の地域と知識を結びつけて考えます。'}</div>
      <div class="mapSource">日本地図：PA4KEV/japan-vector-map（MIT License）</div></div>`;
  };

  const info=document.querySelector('#data .infoCard p');
  if(info)info.innerHTML=`<b id="coreCount">${C.length}</b>知識ユニット＋実際の日本地図を使う都道府県×知識問題＋地図記号＋グラフ・資料＋動的年代問題。問題の組み合わせは毎回変化します。`;
  const vtag=document.querySelector('.vtag');if(vtag)vtag.textContent='v4.2';
  document.title='麻布社会 MASTER 30 v4.2';
  updateDashboard();
})();