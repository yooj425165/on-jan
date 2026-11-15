const el = id => document.getElementById(id);
let busy = false;
async function command(action, data = {}) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  el('message').textContent = '명령 처리 중… 영점/보정은 수 초 걸릴 수 있습니다.';
  try {
    const response = await fetch(`/api/${action}`, {method:'POST', headers:{'Content-Type':'application/json','X-Onjan-Token':token}, body:JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    el('message').textContent = `완료: ${JSON.stringify(result)}`;
  } catch (error) { el('message').textContent = `오류: ${error.message}`; }
  finally { busy = false; document.querySelectorAll('button').forEach(b => b.disabled = false); }
}
document.querySelectorAll('[data-action]').forEach(b => b.onclick = () => command(b.dataset.action));
el('calibration').onsubmit = event => {event.preventDefault(); command('calibrate', {grams:Number(el('grams').value)});};
el('play').onclick = () => command('play', {file:el('track').value});
async function refresh() {
  try {
    const response = await fetch('/api/status', {signal:AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    el('connection').textContent = `연결됨 · ${new Date().toLocaleTimeString()}`;
    for (const [name, key] of [['light','lux'],['weight','g'],['distance','cm']]) {
      const item = state.sensors[name];
      const valid = item?.ok && !item.stale;
      const value = valid ? item.data[key] : null;
      el(`${name}-value`).textContent = value == null ? '—' : Number(value).toFixed(1);
      el(`${name}-status`).textContent = !item ? '초기화 중' : !item.ok ? item.error : item.stale ? '측정값 지연' : name === 'weight' && value == null ? '영점 조정 및 실제 무게추 보정 필요' : name === 'distance' ? (item.data.near ? '물체 접근 감지 (15cm 이내)' : '물체가 감지 범위 밖에 있습니다.') : '정상 수집 중';
    }
    const weight = state.sensors.weight?.data;
    el('weight-detail').textContent = weight ? `RAW ${weight.raw.toFixed(0)} · 변화 ${weight.delta_g == null ? '—' : weight.delta_g.toFixed(1) + 'g'} · 계수 ${weight.counts_per_g ?? '미보정'}` : '';
    const pca = state.sensors.pca;
    el('pca-status').textContent = pca?.ok ? 'PCA9685 / 0x40 응답 정상 · PWM OFF · 실제 전원 유무는 감지할 수 없습니다.' : `PCA9685: ${pca?.error ?? '대기 중'}`;
    el('bus').textContent = `시작 시 I2C 탐색: ${state.i2c_addresses.join(', ') || '장치 없음'}`;
    if (JSON.stringify(state.tracks) !== el('track').dataset.files) {
      el('track').replaceChildren(...state.tracks.map(file => new Option(file, file)));
      el('track').dataset.files = JSON.stringify(state.tracks);
    }
    el('music-status').textContent = state.music.error || (state.music.playing ? `재생 중: ${state.music.playing}` : state.tracks.length ? '재생 대기' : 'music/ 폴더에 WAV 파일이 없습니다.');
    el('audio-device').textContent = state.music.device;
    el('json').textContent = JSON.stringify(state, null, 2);
  } catch (error) {
    el('connection').textContent = '연결 끊김';
    for (const name of ['light','weight','distance']) {el(`${name}-value`).textContent = '—'; el(`${name}-status`).textContent = '서버 연결 실패';}
  } finally {setTimeout(refresh, 1000);}
}
refresh();
