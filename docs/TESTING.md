# 시험 기록 / Test record

판 0.1.0. 시험 자료는 모두 `tests/make_corpus.py`와 `tests/korean_eval_data.py`로 만든 가짜 자료입니다.
[English summary](#english-summary)

## 1. 한 일

### 1.1 GitHub Actions (저장소를 올릴 때마다 새 가상 PC에서)

[워크플로](../.github/workflows/test.yml)가 매번 아래를 돌립니다. 단위 시험은 `python -m unittest discover -s tests -v`(33개)입니다.

| 작업 | 환경 | 하는 일 |
|---|---|---|
| windows-clean | 윈도 러너, Python 3.9·3.13, 추가 설치 없음 | `doctor`, 단위 시험 (도구 시험은 러너에 원래 있는 7-Zip만 실행) |
| windows-tools | 같은 러너 + ExifTool·Czkawka·Everything 설치 | `doctor`, 단위 시험, Program Files에서 용량·찾기·중복 속도 |
| windows-setup-winget | 같은 러너(winget·Chocolatey 둘 다 있음) | `setup`으로 Everything·Czkawka·ExifTool을 winget으로 실제 설치하고 `doctor`가 찾는지 확인 |
| windows-setup-choco | 같은 러너, `LFK_INSTALLER=choco` | `setup`으로 Everything·ExifTool을 Chocolatey로 실제 설치하고 확인 |
| windows-digup | 같은 러너 + DigUp 0.7.0-beta.1 조용히 설치(`/S`) + `digup download-model`, **그래픽 카드 없음** | 단위 시험(DigUp 색인·찾기·문단 고르기, 글자 먼저 찾기 포함), 한국어 성능 시험(DigUp 색인과 글자 먼저 둘 다), 문서 300개를 두 방식으로 처리한 시간 |
| linux | Ubuntu 러너, Python 3.12, ExifTool·7-Zip·Czkawka 설치 | `doctor`, 단위 시험 |
| macos | macOS 러너(Apple Silicon), Python 3.13, 도구 없음 | `doctor`, 단위 시험 (파이썬 기능만. 휴지통 되돌리기 시험은 맥에서 건너뜀) |
| plugin-manifest | Ubuntu 러너 | `claude plugin validate . --strict` |

단위 시험 내용: PDF 글자 읽기(간단한 PDF, 브라우저로 만든 한글 PDF, 글자 없는 스캔 PDF), 글자 먼저 찾기(모델 없이 낱말로, 모델로 뜻으로, 캐시 다시 쓰기), 도구 없이 이름 찾기·용량·중복·빈 폴더·.zip 압축, 복사 미리보기와 덮어쓰지 않기, 정리 계획→이동→되돌리기,
이름 충돌(건너뛰기·이름 바꾸기·대소문자만 다른 이름), 보호 폴더 거절(`\\?\` 경로 포함), 압축 이름·위치 검사와 압축 밖으로 나가는 항목,
`setup`이 확인 없이 설치하지 않는지, 잘못된 인자의 JSON 오류, `--ascii`·`--out`, 휴지통 보내기→되돌리기(복원),
도구가 있을 때 Czkawka와 파이썬 결과 비교, 비슷한 사진, ExifTool 한글 파일 이름, 7-Zip 왕복, WizTree와 파이썬 합계 비교,
Everything 찾기, DigUp 색인→찾기→문단 고르기→발췌 숨기기, `index --media-only`.

### 1.2 도구를 숨긴 가짜 사용자 환경 (`tests/mockenv.py`)

"도구 없음" 시험은 사용자 폴더를 `...\Users\김 철수\` (한글 + 공백)로 바꾸고, PATH를 시스템 폴더만 남기고(맥·리눅스는 빈 폴더),
레지스트리 찾기를 끈 상태(`LFK_NO_REGISTRY=1`)에서 돌립니다. 없는 도구마다 설치 명령·공식 주소·라이선스가 나오는지,
`search`·`similar`·`exif`가 종료 코드 3으로 답하는지, 나머지 기능이 파이썬으로 도는지 확인합니다.
같은 방법으로 도구 일부·전부를 기본 설치 위치에 복사해 한글·공백 사용자 경로에서도 찾고 쓰는지 확인했고,
DigUp 모델이 없을 때 `doctor`가 `download-model` 명령을 알려 주고 `search`가 `model_missing`(종료 코드 3)으로 답하는 것도 확인했습니다.

### 1.3 실제 Claude Code 세션에서 스킬 쓰기

전역 스킬(`~/.claude/skills/local-file-kit` → 저장소의 `skills/local-file-kit` 정션)을 걸고, 저장소와 상관없는 빈 폴더에서
`claude -p`로 새 세션을 띄워 가짜 자료 폴더를 두고 시켰습니다.

| 요청 | 결과 |
|---|---|
| "김치찌개 끓이는 법 파일과 중복 파일 찾아 줘" | 스킬 목록에는 보였으나 **모델이 스킬을 부르지 않고** 셸 명령으로 직접 처리(답은 맞음) |
| description을 고친 뒤 "비행기 좌석 등급 규정 문서, 가장 큰 파일, 중복" | 같음. 18개짜리 작은 폴더라 직접 처리한 것으로 보임 |
| `/local-file-kit 중복 파일과 빈 폴더, 사진 촬영 기기` | `lfk.py doctor → dupes → empty → exif` 순서로 스킬을 써서 정확히 답함. 아무것도 지우지 않고, 지우려면 미리보기 후 확인받겠다고 안내 |

- `${CLAUDE_SKILL_DIR}`는 윈도에서 `C:/Users/<이름>/.claude/skills/local-file-kit`처럼 **슬래시 경로**로 바뀌었고 그대로 동작했습니다.
- 작은 폴더의 간단한 요청에서는 스킬이 저절로 불리지 않을 수 있습니다. 드라이브 전체 찾기·내용 찾기처럼 셸 명령으로 어려운 일에서 저절로 불리는지는 개인 자료가 화면에 나올 수 있어 시험하지 않았습니다.

### 1.4 플러그인

- `claude plugin validate . --strict` 통과(Actions에서도 매번).
- GitHub에서 설치: 따로 만든 설정 폴더(`CLAUDE_CONFIG_DIR`)에서 `claude plugin marketplace add hyunsungko/local-file-kit` → `claude plugin install local-file-kit@local-file-kit` 성공, 받은 사본의 `lfk.py --version` 동작. 실제 사용자 설정은 바뀌지 않았습니다.

### 1.5 코드 검토

별도 검토에서 찾은 문제 11건을 고치고 시험을 더했습니다: 압축을 풀 때 경로를 꼬아 기존 파일을 덮어쓰는 항목, 확장자 없는 압축 이름으로 기존 .7z가 바뀌는 문제, 압축 파일을 원본 폴더 안에 만들 때 자기 자신을 넣는 문제, 대소문자만 다른 이름끼리 이동 중 덮어쓰기, `\\?\`·8.3 짧은 이름·정션으로 보호 폴더 검사를 피하는 경로, 다른 드라이브로 옮기다 원본 삭제가 실패할 때 되돌리기 기록 누락, 되돌리기가 같은 경로에서 지워진 다른 파일을 휴지통에서 꺼낼 수 있던 문제(삭제 시각으로 맞춤), 정규식 찾기에서 조건이 Everything에 전달되지 않던 문제, 명령 앞에 쓴 `--out`이 무시되던 문제, 파일과 폴더 이름이 겹칠 때 복사 결과 오표시, 하위 폴더 정리 계획에서 깨진 링크·`.git` 처리.

### 1.6 처음 받은 PC에서 드러난 문제 (Actions)

새 러너에서만 나는 실패 3가지를 찾아 고쳤습니다. 윈도 러너의 임시 폴더가 8.3 짧은 이름(`C:\Users\RUNNER~1`)이라 휴지통 기록·Czkawka 결과와 경로가 맞지 않았고, 짧은 이름과 맥의 임시 폴더(`/var` → `/private/var`) 때문에 사용자 폴더 보호 검사가 비껴갔고, 리눅스에서 시험용 가짜 환경이 `/usr/bin`의 도구를 숨기지 못했습니다. 경로를 실제 이름으로 바꿔 비교하도록 고쳤습니다.

## 2. 하지 못한 시험

| 시험 | 이유 / 대신 한 것 |
|---|---|
| 새 윈도 11 데스크톱(가상 PC) | 하지 못함. 대신 가짜 사용자 환경 + GitHub Actions 새 윈도 서버 러너 |
| Windows 10 | 하지 못함 |
| `setup`을 일반 사용자 권한 데스크톱에서 실행 (UAC 확인 창이 뜨는 경우) | Actions 러너는 관리자 권한이라 확인 창이 없음 |
| macOS의 Finder 휴지통, 맥용 도구(ExifTool·7-Zip·Czkawka) | Actions macOS 러너에서는 파이썬 기능만 시험 |
| DigUp 맥·리눅스판과 함께 쓰기 | 하지 못함 |
| ARM64 윈도 | 하지 못함. Czkawka는 윈도 ARM64판이 없음 |
| WizTree | Actions에서는 설치하지 않음(개인 사용만 무료). 관리자 권한 실행도 시험하지 않음 |
| 경로 260자 이상, OneDrive 클라우드 전용 파일, 네트워크 드라이브·USB 휴지통 거절 | 코드에는 처리가 있으나 실제 시험 안 함 |
| 영어·한국어 외 언어 윈도의 robocopy 오류 문구 | 시험 안 함 |
| 한국어 PDF·스캔 문서·HWP의 내용 찾기 | 생성기가 한글 PDF를 만들지 않음. 공식판 DigUp은 HWP를 읽지 않음 |
| 수십만 개 실제 색인에서의 한국어 정확도 | 실제 자료로는 시험하지 않음 |
| Microsoft Store의 `python` 가짜 실행 파일만 있는 PC | 하지 못함. SKILL.md에 `py -3` 안내 |

---

## English summary

- GitHub Actions runs on every push, on fresh machines: Windows (Python 3.9 and 3.13; nothing installed / ExifTool,
  Czkawka and Everything installed / `setup` really installing tools with Chocolatey and with winget / DigUp silently
  installed with its model and no GPU, plus the Korean search evaluation), Ubuntu with tools, macOS without tools, and
  `claude plugin validate --strict`. 33 unit tests, including PDF text reading (also a browser-made Korean PDF) and
  text-first search.
- A pretend user profile (user folder `김 철수` with a space, PATH cut down, registry lookups off) checks every Python
  fallback, exit code 3 with install advice for missing tools, tools found from a Korean/space path, and
  `model_missing` when DigUp has no model.
- Real Claude Code session (global skill via junction, empty folder): `/local-file-kit ...` used the skill correctly
  (`${CLAUDE_SKILL_DIR}` became a forward-slash path on Windows). For small natural requests on an 18-file folder the
  model answered with shell commands instead of loading the skill.
- Plugin installed from GitHub (`hyunsungko/local-file-kit`) into an isolated config.
- Not tested: a fresh Windows 11 desktop VM, Windows 10, `setup` under a non-admin account (UAC prompts), macOS Trash
  and macOS tools, ARM64, DigUp on macOS/Linux, WizTree in CI, paths over 260 characters, cloud-only files,
  network/USB drives, Korean PDFs/HWP, accuracy on a large real index.
