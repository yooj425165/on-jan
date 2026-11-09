# Spotify 재생 테스트

`spotify_play.py`는 Spotify Web API로 Spotify Connect 기기의 음악 재생을 제어합니다.
Python 자체에서 오디오를 디코딩하거나 스피커로 출력하지 않습니다.
Spotify Premium 계정과 같은 계정으로 로그인한 Spotify 앱/Connect 기기가 필요합니다.
라즈베리파이에서 실행해도 소리는 선택한 Spotify 기기에서 나옵니다.

## 준비

1. Spotify Developer Dashboard(https://developer.spotify.com/dashboard)에서 앱을 만듭니다.
2. 앱의 Redirect URI에 `http://127.0.0.1:8888/callback`을 정확히 등록합니다.
3. 개발 모드 앱은 Dashboard에서 테스트 계정의 접근 권한을 확인합니다.
4. 프로젝트 루트에서 아래 명령을 실행합니다. 실제 Client ID와 Secret으로 바꾸세요.

```sh
source .venv/bin/activate
python -m pip install -r test/requirements-spotify.txt
export SPOTIPY_CLIENT_ID='your-client-id'
export SPOTIPY_CLIENT_SECRET='your-client-secret'
export SPOTIPY_REDIRECT_URI='http://127.0.0.1:8888/callback'
```

기존 Ubuntu 환경의 가상환경 이름이 `venv`라면 `source venv/bin/activate`를 사용합니다.
환경 변수는 현재 터미널에 적용됩니다. `.env` 파일을 자동으로 읽지는 않습니다.
Client Secret을 코드에 넣거나 Git에 커밋하지 마세요.

## 실행

매번 옵션을 입력하지 않으려면 `test/spotify_play.py` 상단을 수정하세요.

```python
DEVICE = "실제 Spotify Connect 기기 이름 또는 ID"
SONG_QUERY = "Dynamite BTS"
SONG_URI = ""
```

`DEVICE`가 비어 있으면 재생 대신 기기 목록을 출력합니다. 목록에서 라즈베리파이의
기기 이름이나 ID를 복사해 설정하세요. 라즈베리파이에서 Spotify Connect 수신 프로그램이
실행 중이어야 목록에 나타납니다. 물리 스피커나 오디오 단자 이름을 입력하는 것은 아닙니다.
`SONG_URI`에 곡 링크를 넣으면 검색 대신 해당 곡을 사용합니다.

설정 후에는 옵션 없이 실행할 수 있습니다. 인증 환경 변수 설정은 여전히 필요합니다.

```sh
.venv-spotify/bin/python test/spotify_play.py
```

위 명령은 `.venv-spotify` 가상환경을 만든 경우입니다. 다른 가상환경을 사용하면 해당
환경의 Python 경로로 바꾸세요. 명령줄 옵션을 주면 코드에 적은 곡과 기기 설정보다 우선합니다.

Spotify 앱을 열어 로그인한 다음 실행합니다. 최초 실행 시 브라우저에서 권한을 승인합니다.
브라우저와 스크립트는 같은 컴퓨터에서 실행하는 것이 가장 간단합니다.

```sh
# 기기 이름과 ID 확인
python test/spotify_play.py --devices

# 검색 결과 첫 번째 곡 재생
python test/spotify_play.py --query "Dynamite BTS"

# 특정 기기에서 재생 (출력된 실제 기기 ID로 교체)
python test/spotify_play.py --query "Dynamite BTS" --device 'device-id'

# 곡 링크 또는 spotify:track:... URI로 정확한 곡 지정
python test/spotify_play.py --uri 'https://open.spotify.com/track/0t1kP63rueHleOhQkYSXFY'
```

기기를 지정하지 않으면 현재 활성 기기를 선택합니다. 활성 기기가 없고 제어 가능한 기기가
하나뿐이면 그 기기를 사용합니다. 여러 기기 중 선택할 수 없으면 `--device`를 요청합니다.
기기 이름이 중복되면 ID로 지정하세요. 재생 요청은 해당 기기의 기존 재생을 변경합니다.

인증 토큰은 저장소 밖 `~/.cache/onjan/spotify-token.json`에 저장됩니다.
다른 계정으로 인증하려면 해당 캐시 파일을 삭제하고 다시 실행합니다.
기기가 검색되지 않으면 Spotify 앱에서 곡을 한 번 재생한 뒤 다시 확인하세요.
403 오류는 Premium 여부, 개발 모드의 사용자 접근 권한, 기기 제한을 확인하세요.
