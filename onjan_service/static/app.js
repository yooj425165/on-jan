const $ = id => document.getElementById(id);
let sending = false, running = false, connected = false, predictionTime = null;
function buttons() {document.querySelectorAll('button').forEach(b => b.disabled = sending || running || !connected);}
async function command(action, data={}) {
  if (sending || running) return;
  sending = true; buttons();
  try {
    const response = await fetch(`/api/commands/${action}`, {method:'POST', headers:{'Content-Type':'application/json','X-Onjan-Token':token}, body:JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    running = true;
    $('message').textContent = `처리 중 / ${action} (${result.job_id.slice(0,8)})`;
  } catch(error) {$('message').textContent = error.message;}
  finally {sending = false; buttons();}
}
document.querySelectorAll('[data-action]').forEach(b => b.onclick = () => command(b.dataset.action));
$('predict').onsubmit = e => {e.preventDefault(); command('predict',{source:'manual',lux:Number($('lux').value),weight_g:Number($('grams').value),distance_cm:Number($('cm').value)});};
$('sensor-predict').onclick = () => command('predict',{source:'sensors'});
$('play').onclick = () => command('play',{file:$('tracks').value});
$('calibrate').onsubmit = e => {e.preventDefault();command('calibrate',{grams:Number($('known').value)});};
$('arm').onclick = () => command('automation',{enabled:true});
$('disarm').onclick = () => command('automation',{enabled:false});
async function poll() {
  try {
    const response = await fetch('/api/status',{signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    connected = true;
    running = state.phase === 'starting' || state.job?.status === 'running';
    $('connection').textContent = `${state.phase} · ${new Date().toLocaleTimeString()}`;
    for (const [name,key,unit] of [['light','lux','lux'],['weight','g','g'],['distance','cm','cm']]) {
      const item=state.sensors[name];
      const value=item?.ok && !item.stale ? item.data[key] : null;
      $(name).textContent = value == null ? '—' : `${Number(value).toFixed(1)} ${unit}`;
      $(`${name}-error`).textContent = item?.error || (item?.stale ? '측정 지연' : value == null ? '측정 준비 / 보정 필요' : '정상 수집');
    }
    if ($('tracks').dataset.files !== JSON.stringify(state.tracks)) {
      $('tracks').replaceChildren(...state.tracks.map(file => new Option(file,file)));
      $('tracks').dataset.files = JSON.stringify(state.tracks);
    }
    $('player').textContent = state.music.error || (state.music.playing ? `재생 중: ${state.music.playing}` : `재생 대기 · ${state.music.device}`);
    $('microphone').textContent = JSON.stringify(state.microphone);
    const labels={disabled:'감지 꺼짐',wait_removal:'컵 제거 대기',waiting:'컵 올리기 대기',moving:'이동 중 (시뮬레이션)',holding:'위치 유지 (시뮬레이션)',returning:'복귀 중 (시뮬레이션)',sensor_unavailable:'무게 센서 오류 / 최신값 없음'};
    $('automation').textContent = `${labels[state.automation.state]} · 완료 ${state.automation.cycles}회`;
    if (state.job) $('message').textContent = `${state.job.action} · ${state.job.status}${state.job.error ? ': '+state.job.error : ''}`;
    const prediction=state.prediction;
    if (prediction && prediction.created_at !== predictionTime) {
      predictionTime=prediction.created_at;
      $('scores').replaceChildren();$('recommendations').replaceChildren();
      for (const [key,label] of [['calmness','차분함'],['energy','활기참'],['comfort','쾌적함']]) {
        const p=document.createElement('p'),meter=document.createElement('meter');
        meter.min=0;meter.max=1;meter.value=prediction.scores[key];meter.setAttribute('aria-label',label);
        p.append(`${label} ${prediction.scores[key].toFixed(3)}`,meter);$('scores').append(p);
      }
      $('prediction-note').textContent = `${prediction.notice} / ${prediction.input_source} / ${JSON.stringify(prediction.inputs)} / ${new Date(prediction.created_at*1000).toLocaleTimeString()}`;
      for (const [i,track] of prediction.recommendations.entries()) {
        const button=document.createElement('button');button.textContent=`${i+1}. ${track.file} · 재생`;
        button.onclick=()=>command('play',{file:track.file});$('recommendations').append(button);
      }
      if (!prediction.recommendations.length) $('recommendations').textContent='등록된 WAV를 music/에 복사하세요.';
    }
    $('diagnostics').textContent=JSON.stringify(state,null,2);
  } catch(error) {
    connected=false;$('connection').textContent='연결 끊김';
    for (const name of ['light','weight','distance']) {$(name).textContent='—';$(`${name}-error`).textContent='서버 연결 없음';}
  } finally {buttons();setTimeout(poll,1000);}
}
buttons();poll();
