const el = id => document.getElementById(id);
let motorReady=false;
let points = [], last = null, pending = null, sending = false, valid = false, tared = false, busy = false;
function controls() {
  el('tare').disabled = !valid || sending || !!pending || busy;
  el('cycle').disabled = !motorReady || sending || !!pending || busy;
  el('save').disabled = el('tare').disabled || !tared;
}
function chart() {
  const lo=Math.min(...points), hi=Math.max(...points);
  el('line').setAttribute('points',points.map((v,i)=>`${i*600/Math.max(1,points.length-1)},${hi===lo?50:95-90*(v-lo)/(hi-lo)}`).join(' '));
  el('range').textContent = points.length ? `최소 ${lo.toFixed(1)} · 최대 ${hi.toFixed(1)} · 변동폭 ${(hi-lo).toFixed(1)} counts` : '측정 대기';
}
function clearReading() {
  valid=false; tared=false; points=[]; last=null; chart();
  for(const id of ['raw','mass','factor']) el(id).textContent='—';
}
async function poll() {
  try {
    const r=await fetch('/api/status',{signal:AbortSignal.timeout(5000)});
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    const s=await r.json(), item=s.sensors.weight, d=item?.data;
    motorReady=s.servo_control==='manual_test' && s.sensors.pca?.ok && !s.sensors.pca?.stale;
    el('motor-status').textContent=motorReady?'수동 시험 허용':'외부 전원 확인 또는 PCA9685 연결 필요';
    busy=s.phase==='starting' || s.job?.status==='running';
    if(pending && s.job?.id===pending && !busy){
      el('message').textContent=s.job.error || (s.job.action==='servo_cycle'?'양쪽 복귀 명령 완료 · PWM OFF':s.job.action==='tare'?'영점 완료.':'보정 저장 완료. 무게추를 제거하고 0g을 확인하세요.');pending=null;
    }else if(pending && s.job && s.job.id!==pending && !busy){pending=null;}
    valid=item?.ok && !item.stale && Number.isFinite(d?.raw);
    if(valid){
      tared=d.tared;
      el('health').textContent=tared?(d.g==null?'영점 완료 · 보정 필요':'무게 측정 중'):'영점 조정 필요 · RAW 측정 중';
      el('raw').textContent=d.raw.toFixed(1); el('mass').textContent=d.g==null?'—':d.g.toFixed(1); el('factor').textContent=d.counts_per_g==null?'—':Number(d.counts_per_g.toPrecision(5));
      if(last!==item.updated_at){points.push(d.raw);if(points.length>60)points.shift();chart();last=item.updated_at;}
    }else{clearReading();el('health').textContent=item?.error || (item?.stale?'측정 지연':'로드셀 측정값 없음');}
  }catch(e){motorReady=false;clearReading();el('health').textContent=`상태 조회 실패: ${e.message}`;}
  finally{controls();setTimeout(poll,500);}
}
async function command(action,data){
  sending=true;controls();
  try{
    const r=await fetch(`/api/commands/${action}`,{method:'POST',headers:{'Content-Type':'application/json','X-Onjan-Token':token},body:JSON.stringify(data)});
    const j=await r.json();if(!r.ok)throw new Error(j.error);pending=j.job_id;el('message').textContent=action==='servo_cycle'?'양팔 이동·유지·복귀 중':'측정 중 · 물체를 움직이지 마세요.';
  }catch(e){el('message').textContent=e.message;}
  finally{sending=false;controls();}
}
el('cycle').onclick=()=>command('servo_cycle',{});
el('tare').onclick=()=>command('tare',{});
el('cal').onsubmit=e=>{e.preventDefault();if(!el('save').disabled)command('calibrate',{grams:Number(el('known').value)});};
poll();
