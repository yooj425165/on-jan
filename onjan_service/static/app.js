const $ = id => document.getElementById(id);
let sending = false, running = false, connected = false;
let micEnabled = false;
function buttons() {document.querySelectorAll('button').forEach(b => b.disabled = sending || running || !connected || (!micEnabled && b.matches('[data-action="measure"]')));}
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
$('choose').onclick = () => command('choose',{mood:$('mood').value});
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
    const addresses = state.i2c_addresses || [];
    $('i2c-info').textContent = state.phase === 'manual_only' ? '수동 모드: I2C 탐색 안 함' : state.phase === 'starting' ? 'I2C 초기화 중' : `시작 시 I2C: ${addresses.join(', ') || '확인된 주소 없음'} · BH1750 예상: 0x23 / 0x5c`;
    const mic = state.microphone;
    const live = mic.status === 'recording' && Number.isFinite(mic.level_dbfs);
    $('mic-level').value = live ? Math.max(-80, mic.level_dbfs) : -80;
    micEnabled = mic.status !== 'disabled';
    $('microphone').textContent = live ? `녹음 중 · ${mic.level_dbfs} dBFS` : mic.status === 'restoring' ? '측정 완료 · 센서 복구 중' : !micEnabled ? '비활성 · arecord -l로 녹음 장치를 확인하고 --microphone 옵션으로 통합 서버를 시작하세요.' : mic.status === 'error' ? `측정 실패: ${mic.error}` : mic.data ? `최근 측정: ${mic.data.rms_dbfs} dBFS (RMS) · 피크 ${mic.data.peak_dbfs} dBFS · ${mic.data.device}` : '측정 대기 · 버튼을 눌러 녹음 장치 응답을 확인하세요.';
    const labels={disabled:'감지 꺼짐',wait_removal:'컵 제거 대기',waiting:'컵 올리기 대기',moving:'이동 중 (시뮬레이션)',holding:'위치 유지 (시뮬레이션)',returning:'복귀 중 (시뮬레이션)',sensor_unavailable:'무게 센서 오류 / 최신값 없음'};
    $('automation').textContent = `${labels[state.automation.state]} · 완료 ${state.automation.cycles}회`;
    if (state.job) $('message').textContent = `${state.job.action} · ${state.job.status}${state.job.error ? ': '+state.job.error : ''}`;
    if (!$('mood').options.length) $('mood').replaceChildren(...state.moods.map(m=>new Option(m,m)));
    const sel = state.selection;
    $('selection').textContent = sel ? `${sel.mood} · ${sel.reason} · ${sel.tracks.length}곡 ${sel.error || ''}` : '분위기를 측정하거나 직접 선택하세요.';
    $('diagnostics').textContent=JSON.stringify(state,null,2);
  } catch(error) {
    connected=false;$('mic-level').value=-80;$('microphone').textContent='서버 연결 없음';$('connection').textContent='연결 끊김';
    for (const name of ['light','weight','distance']) {$(name).textContent='—';$(`${name}-error`).textContent='서버 연결 없음';}
  } finally {buttons();setTimeout(poll,connected && running ? 120 : 1000);}
}
buttons();poll();
