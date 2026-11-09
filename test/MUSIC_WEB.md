# 로컬 WAV 웹 플레이어

Spotify 없이 Flask 웹 서버와 `aplay`로 재생합니다. Python 3.9 이상이 필요합니다.
브라우저는 리모컨이며 소리는 서버를 실행한 라즈베리파이에서 나옵니다.

라즈베리파이의 온잔 프로젝트 폴더에서:

```sh
python3 -m venv .venv-music
.venv-music/bin/python -m pip install -r test/requirements-music.txt
python3 test/download_music.py
.venv-music/bin/python test/music_web.py
```

가상환경 생성과 패키지 설치는 처음 한 번만 합니다. `venv` 생성 오류가 나면 Ubuntu에서
`sudo apt install python3-venv`를 먼저 실행하세요. 이후에는 마지막 서버 실행 명령만 사용합니다.
Flask 개발 서버를 단일 프로세스로 실행하며, 리로더/디버그 모드는 꺼져 있습니다.
여러 서버 프로세스를 동시에 실행하지 마세요. 이 플레이어는 단일 프로세스용입니다.

같은 네트워크의 PC/휴대폰에서 `http://라즈베리파이IP:5007`을 엽니다.
예: `http://172.20.10.2:5007`. 재생/정지 버튼으로 조작합니다. 다른 곡을 재생하면 이전 곡은 멈춥니다.
서버 종료는 Ctrl+C이며 음악도 정지합니다. 자동 다음 곡, 일시정지, AI 추천은 구현하지 않았습니다.

`music_web.py` 상단의 `OUTPUT_DEVICE`에 USB 장치가 지정되어 있습니다:

```python
OUTPUT_DEVICE = "plughw:CARD=UACDemoV10,DEV=0"
```

다운로더는 Wikimedia Commons의 바흐 피아노 연주 2곡(약 39 MB)을 원본 WAV로 저장합니다.
연주자는 eldüendesüarez, 녹음 라이선스는 CC BY-SA 4.0입니다. 출처와 라이선스는
`music/sources.json`과 웹 화면에 표시됩니다. 파일을 공유할 때 출처/라이선스도 함께 제공하고,
편집본을 배포하면 해당 라이선스의 동일조건변경허락 조건을 지키세요.
추가 WAV는 `music/`에 넣으면 표시됩니다. 추가 파일의 사용 권한과 출처는 별도로 확인하세요.
다운로드는 인터넷이 필요하지만 이후 재생은 오프라인으로 가능합니다.

음원은 Git에서 제외하므로 다른 기기에서는 다운로드 명령을 다시 실행해야 합니다.
`aplay`가 없으면 `sudo apt install alsa-utils`로 설치하세요.
장치가 사용 중이면 기존 WAV 플레이어나 Raspotify 재생을 멈추세요.
필요하다면 `sudo systemctl stop raspotify`로 서비스를 잠시 중지할 수 있습니다.

기본 포트는 5007입니다. `--port 5008`로 바꿀 수 있습니다.
이 서버는 로그인 없는 신뢰된 로컬 네트워크 테스트용입니다. 인터넷 포트 포워딩이나 학교 전체에
공개하지 마세요. 로컬에서만 확인하려면 `--host 127.0.0.1`을 사용하세요.
macOS에서도 목록/UI 확인은 가능하지만 실제 USB 재생에는 Linux의 `aplay`가 필요합니다.
