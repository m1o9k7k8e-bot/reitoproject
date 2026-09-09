// v3.1: yesterday-specific relearn control.
(function(){
  function yesterday(){const d=new Date();d.setDate(d.getDate()-1);return d.toISOString().slice(0,10)}
  window.resetYesterdayLearning=function(){
    const y=yesterday();
    const targets=C.filter(c=>st(c).last===y);
    if(!targets.length){alert('昨日学習した知識はありません。');return;}
    if(!confirm('昨日触れた'+targets.length+'件を、今日もう一度出題対象に戻しますか？\n累積正答率と間違い履歴は残します。')) return;
    targets.forEach(c=>{const x=st(c);x.box=0;x.due=day();});
    save();
    alert('昨日の学習分を再出題キューに戻しました。');
  };
  const cards=[...document.querySelectorAll('#data .card')];
  const box=cards.find(x=>x.textContent.includes('再学習・リセット'));
  if(box){
    const first=box.querySelector('button');
    const b=document.createElement('button');
    b.className='btn sub';b.style.marginTop='8px';b.textContent='昨日の学習を再出題';b.onclick=resetYesterdayLearning;
    if(first&&first.nextSibling) box.insertBefore(b,first.nextSibling); else box.appendChild(b);
  }
})();