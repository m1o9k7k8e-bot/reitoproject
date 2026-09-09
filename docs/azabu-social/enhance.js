// v3 enhancements: active recall, mini-evidence mode, targeted relearn/reset controls.
(function(){
  const baseTypeLabel = typeLabel;
  typeLabel = function(t){
    const m={recall:'白紙想起',evidence:'ミニ資料'};
    return m[t] || baseTypeLabel(t);
  };

  const baseVariants = variants;
  variants = function(c){
    const v=baseVariants(c);
    v.push({
      key:c.id+'-recall', card:c, type:'recall',
      prompt:c.definition+'。語句を声に出して答えてから「答えを見る」を押してください。',
      answer:c.term
    });
    if(c.reason){
      const opts=[c.term,...distractTerms(c)];
      v.push({
        key:c.id+'-evidence', card:c, type:'evidence',
        prompt:'【資料A】'+c.definition+'\n【資料B】'+c.reason+'\nこの2つの資料と最も直接結びつくテーマ・語句は？',
        answer:c.term, options:opts
      });
    }
    return v;
  };

  const baseEligible = eligible;
  eligible = function(m){
    if(m==='recall') return allVariants().filter(v=>v.type==='recall');
    if(m==='evidence') return allVariants().filter(v=>v.type==='evidence');
    return baseEligible(m);
  };

  const baseChoose = choose;
  choose = function(m){
    if(m==='recall') return chooseFrom(eligible(m),12);
    if(m==='evidence') return chooseFrom(eligible(m),10);
    if(m!=='daily') return baseChoose(m);

    const av=allVariants(), count=20, d=dayNo(), picked=[];
    const add=(arr,n)=>{
      for(const v of arr){
        if(picked.length>=count||n<=0) break;
        if(!picked.some(x=>x.key===v.key)){picked.push(v);n--;}
      }
    };
    if(d<=3){
      for(const dom of ['歴史','地理','公民']){
        const unseen=shuffle(av.filter(v=>v.card.domain===dom && st(v.card).a===0 && !['why','evidence'].includes(v.type)));
        add(unseen, dom==='歴史'?6:dom==='地理'?7:4);
      }
      add(shuffle(av.filter(v=>v.type==='recall')),3);
    }else{
      const ranked=av.slice().sort((a,b)=>weakness(b.card)-weakness(a.card)+(Math.random()-.5)*1.2);
      add(ranked.filter(v=>st(v.card).due<=day() && !['why','evidence'].includes(v.type)),8);
      add(shuffle(ranked.filter(v=>st(v.card).a===0 && !['why','evidence'].includes(v.type))),4);
      add(shuffle(ranked.filter(v=>v.type==='recall')),4);
      add(shuffle(ranked.filter(v=>v.type==='why')),d>=21?3:2);
      add(shuffle(ranked.filter(v=>v.type==='evidence')),d>=14?3:2);
      add(ranked,count-picked.length);
    }
    return shuffle(picked).slice(0,count);
  };

  const baseRender = render;
  render = function(){
    baseRender();
    const q=session[ix];
    if(!q) return;
    if(q.type==='recall'){
      document.getElementById('answerArea').innerHTML =
        '<div class="recallbox"><p class="small">選択肢なし。まず頭の中か声で答えます。</p>'+ 
        '<button class="btn" onclick="showRecallAnswer()">答えを見る</button></div>';
    }
    if(q.type==='evidence'){
      document.getElementById('answerArea').innerHTML =
        '<div class="options">'+shuffle(q.options).map((x,i)=>
        `<button class="option" data-v="${enc(x)}" onclick="pick(this)">${String.fromCharCode(65+i)}. ${esc(x)}</button>`
        ).join('')+'</div>';
      document.getElementById('prompt').innerHTML=esc(q.prompt).replace(/\n/g,'<br>');
    }
  };

  window.showRecallAnswer=function(){
    if(locked) return;
    const q=session[ix], c=q.card, f=document.getElementById('feedback');
    f.className='feedback';
    f.innerHTML=`<b>答え：${esc(c.term)}</b><div style="margin-top:7px">${esc(c.definition)}</div>`+
      (c.reason?`<div class="link"><b>なぜ？</b> ${esc(c.reason)}</div>`:'')+
      (c.links?.length?`<div class="link"><b>🔗つなぐ：</b> ${c.links.map(esc).join(' → ')}</div>`:'')+
      `<div class="score3"><button class="s0" onclick="gradeRecall(0)">言えなかった</button><button class="s1" onclick="gradeRecall(1)">惜しい</button><button class="s2" onclick="gradeRecall(2)">言えた</button></div>`;
  };
  window.gradeRecall=function(n){
    if(locked) return;
    record(session[ix],n,2);
    const sc=document.querySelector('.score3');
    if(sc) sc.innerHTML='<b>登録しました。</b>';
    document.getElementById('next').classList.remove('hidden');
  };

  function cardById(id){return C.find(c=>c.id===id)}
  function resetCard(c, hard){
    if(!c) return;
    if(hard){
      S.concept[c.id]={a:0,s:0,box:0,due:day(),last:null};
      Object.keys(S.variant).filter(k=>k.startsWith(c.id+'-')).forEach(k=>delete S.variant[k]);
    }else{
      const x=st(c); x.box=0; x.due=day();
    }
  }
  window.relearnOne=function(id){
    const c=cardById(id); if(!c) return;
    resetCard(c,true); save();
    alert('「'+c.term+'」を未習状態に戻しました。今日から再出題します。');
    if(!document.getElementById('weakpage').classList.contains('hidden')) renderWeak();
    if(!document.getElementById('note').classList.contains('hidden')) renderNotes();
  };
  window.resetWeakLearning=function(){
    const mistakeTerms=new Set(S.mistakes.map(m=>m.term));
    const targets=C.filter(c=>mistakeTerms.has(c.term)||initialWeakTerms.has(c.term));
    const learned=targets.filter(c=>st(c).a>0);
    if(!learned.length){alert('リセット対象の学習済み弱点はまだありません。');return;}
    if(!confirm(learned.length+'件の弱点を「未習」に戻して再診断しますか？\n間違い履歴と日別記録は残します。')) return;
    learned.forEach(c=>resetCard(c,true)); save();
    alert(learned.length+'件を再学習対象に戻しました。');
  };
  window.resetTodayLearning=function(){
    const targets=C.filter(c=>st(c).last===day());
    if(!targets.length){alert('今日学習した知識はありません。');return;}
    if(!confirm('今日触れた'+targets.length+'件を、今日もう一度出題対象に戻しますか？\n累積正答率は消しません。')) return;
    targets.forEach(c=>resetCard(c,false)); save();
    alert('今日の学習分を再出題キューに戻しました。');
  };
  window.retestMastered=function(){
    const targets=C.filter(c=>master(c)>=3);
    if(!targets.length){alert('定着判定の知識はまだありません。');return;}
    if(!confirm('定着判定の'+targets.length+'件を再テスト対象に戻しますか？\n過去の正答履歴は残します。')) return;
    targets.forEach(c=>resetCard(c,false)); save();
    alert('定着済み知識を再テスト対象に戻しました。');
  };

  renderWeak = function(){
    for(const [d,id] of [['歴史','mapH'],['地理','mapG'],['公民','mapC']])
      document.getElementById(id).innerHTML=unitStats(d).map(x=>
        `<div class="unit"><div class="unithead"><span>${x.u}</span><span class="small">${x.seen}/${x.total}</span></div><div class="bar"><div style="width:${Math.round(x.score*100)}%"></div></div></div>`
      ).join('');
    document.getElementById('weakList').innerHTML=topWeak(15).map((c,i)=>
      `<div class="weakitem"><span><b>${i+1}. ${esc(c.term)}</b><br><span class="small">${c.domain} / ${c.unit}</span></span><span><span class="small">弱点 ${weakness(c).toFixed(1)}</span><br><button class="miniReset" onclick="relearnOne('${c.id}')">↻ 再学習</button></span></div>`
    ).join('');
  };

  renderNotes = function(){
    const e=document.getElementById('mistakes');
    e.innerHTML=S.mistakes.length?S.mistakes.slice(0,50).map(m=>{
      const c=C.find(x=>x.term===m.term);
      return `<details><summary>${m.date}｜${m.domain}｜${esc(m.term)}</summary><p>${m.unit} / ${typeLabel(m.type)} / 得点 ${m.score}/${m.max}</p>${c?`<button class="miniReset" onclick="relearnOne('${c.id}')">この知識を未習に戻す</button>`:''}</details>`;
    }).join(''):'<p class="small">まだ間違いはありません。</p>';
  };

  const homeGrid=document.querySelector('#home .grid');
  if(homeGrid){
    const recall=document.createElement('div'); recall.className='card';
    recall.innerHTML='<h2>⚡ 白紙想起</h2><p>選択肢なし。声に出して答え、言えた/惜しい/言えないで自己採点。知識の穴発見に最強。</p><button class="btn" onclick="start(\'recall\')">白紙想起12問</button>';
    homeGrid.appendChild(recall);
    const ev=document.createElement('div'); ev.className='card';
    ev.innerHTML='<h2>📊 ミニ資料</h2><p>2つの手掛かりを結びつけて語句を特定。麻布の資料→推論への橋渡し。</p><button class="btn sub" onclick="start(\'evidence\')">資料リンク10問</button>';
    homeGrid.appendChild(ev);
  }

  const dataGrid=document.querySelector('#data .grid');
  if(dataGrid){
    const box=document.createElement('div'); box.className='card';
    box.innerHTML='<h3>↻ 再学習・リセット</h3><p>全データを消さずに、必要な範囲だけやり直せます。</p>'+ 
      '<button class="btn sub" onclick="resetTodayLearning()">今日の学習を再出題</button>'+ 
      '<button class="btn sub" style="margin-top:8px" onclick="resetWeakLearning()">学習済み弱点を未習に戻す</button>'+ 
      '<button class="btn sub" style="margin-top:8px" onclick="retestMastered()">定着済みを再テスト</button>'+ 
      '<p class="small">「弱点を未習に戻す」は間違い履歴を残したまま、その知識の習熟度と出題形式の履歴だけを初期化します。</p>';
    dataGrid.appendChild(box);
  }

  const style=document.createElement('style');
  style.textContent='.miniReset{border:1px solid #cbd5e1;background:#fff;color:#0f3557;border-radius:9px;padding:6px 9px;font-weight:700;font-size:12px;margin-top:5px}.recallbox{padding:12px 0}.weakitem>span:last-child{text-align:right}';
  document.head.appendChild(style);

  dash();
})();