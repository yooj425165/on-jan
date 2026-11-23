const el = id => document.getElementById(id);
let sending = false, waiting = false, requestError = '';
el('capture').onclick = async () => {
  sending = true;
  requestError = '';
  el('capture').disabled = true;
  el('message').textContent = '측정 요청 중';
  try {
    const r = await fetch('/api/commands/capture', {method:'POST', headers:{'Content-Type':'application/json','X-Onjan-Token':token}, body:'{}'});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  } catch (e) { requestError = e.message; el('message').textContent = requestError; }
  finally { sending = false; }
};
async function refresh() {
  try {
    const r = await fetch('/api/status', {signal:AbortSignal.timeout(5000)});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const s = await r.json(), mic = s.microphone, data = mic.data;
    waiting = s.job?.status === 'running';
    const live = mic.status === 'recording' && Number.isFinite(mic.level_dbfs);
    el('live').value = live ? Math.max(-80, mic.level_dbfs) : -80;
    el('level').textContent = live ? ` ${mic.level_dbfs} dBFS` : ' 대기';
    el('capture').disabled = sending || waiting || s.phase === 'starting' || mic.status === 'disabled' || !!s.music.playing;
    const error = mic.error || (s.job?.action === 'capture' && s.job.error);
    el('message').textContent = requestError || error || (mic.status === 'disabled' ? '마이크 비활성' : s.music.playing ? '측정하려면 통합 화면에서 음악을 정지하세요.' : live ? '녹음 중' : waiting ? '작업 진행 중' : data ? '측정 완료' : '측정 대기');
    if (data) {
      el('rms').textContent = `${data.rms_dbfs} dBFS`;
      el('peak').textContent = `${data.peak_dbfs} dBFS`;
      el('clip').textContent = `${(data.clipping_ratio*100).toFixed(2)}%`;
      el('device').textContent = `${new Date(mic.measured_at*1000).toLocaleTimeString()} · ${data.device}`;
    }
  } catch (e) {
    el('capture').disabled = true; el('live').value = -80; el('level').textContent = '';
    el('message').textContent = `상태 조회 실패: ${e.message}`;
  } finally { setTimeout(refresh, waiting || sending ? 120 : 500); }
}
refresh();
