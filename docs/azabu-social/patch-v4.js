// v4 final polish: preserve answered position when pausing, avoid revealing timeline answers,
// and label stacked-chart categories correctly.
(function(){
  const originalPause = pauseSession;
  pauseSession = function(){
    if(!S.active){ showPage('home',document.querySelector('[data-p="home"]')); return; }
    S.active.index = Math.max(S.active.index||0, ix);
    S.active.score = score; S.active.possible = possible; saveState();
    document.getElementById('quiz').classList.add('hidden');
    document.querySelector('.tabshell').classList.remove('hidden');
    showPage('home',document.querySelector('[data-p="home"]'));
  };

  resumeSession = function(){
    if(!S.active) return;
    mode=S.active.mode; session=S.active.session||[]; score=S.active.score||0; possible=S.active.possible||0;
    if((S.active.index||0)>=session.length){ ix=session.length; finishSession(); return; }
    ix=S.active.index||0; locked=false; openQuiz(); renderQuestion();
  };

  function blankHistoryTrack(){
    const segs=(V.eras||[]).map(e=>`<div class="trackSeg">${e.name}</div>`).join('');
    return `<div class="timelineQuestion"><div class="eraRange">全歴史のどこに入る出来事か考える</div><div class="track">${segs}</div><div class="trackNote">左＝古い　→　右＝新しい</div></div>`;
  }
  const oldRenderContext=renderContext;
  renderContext=function(q){
    if(q.type==='timeline'){
      document.getElementById('contextVisual').innerHTML=blankHistoryTrack();
      return;
    }
    oldRenderContext(q);
  };

  const oldRenderGraph=renderGraph;
  renderGraph=function(g){
    const html=oldRenderGraph(g);
    if(!g||g.kind!=='stacked') return html;
    const legend=`<div class="legend">${g.labels.map(x=>`<span>${esc(x)}</span>`).join('')}</div>`;
    return html.replace(/<div class="legend">[\s\S]*?<\/div><div class="chartNote">/,legend+'<div class="chartNote">');
  };
})();