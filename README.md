# local-file-kit

내 컴퓨터 안의 파일을 **이름으로, 내용과 뜻으로** 찾고, 용량·중복·사진 정보를 보고, **미리보기와 되돌리기가 있는** 정리까지 하는 Claude Code 스킬입니다.
흩어져 있는 무료 도구(Everything, DigUp + EmbeddingGemma 2, WizTree, Czkawka, ExifTool, 7-Zip, robocopy)를 명령 하나(`lfk.py`)로 묶었습니다. 도구가 없으면 파이썬으로 대신하거나, 무엇을 설치하면 되는지 알려 줍니다.

[English](#english) · [사양과 한계](docs/SPECS.md) · [시험 기록](docs/TESTING.md) · [명령 설명](skills/local-file-kit/reference/commands.md) · [변경 기록](CHANGELOG.md)

## 할 수 있는 일

| 하고 싶은 일 | 명령 | 쓰는 도구 | 도구가 없으면 |
|---|---|---|---|
| 이름 일부로 파일 찾기 | `find` | Everything (es.exe) | 지정한 폴더를 파이썬으로 훑음(느림) |
| 폴더 안 문서를 내용·뜻으로 찾기 (한국어·영어) | `search --root 폴더` | 파일 글자를 바로 읽음 + EmbeddingGemma 2 (DigUp 안의 모델), 색인 없음 | 같은 낱말로 찾음 |
| 사진·스크린샷·스캔 PDF를 뜻으로 찾기 | `index --media-only`, `search` | DigUp 색인 | 쓸 수 없음(설치 안내) |
| 찾은 파일 안에서 맞는 문단 고르기 | `search --passages 3` | EmbeddingGemma 2 | 같은 낱말로 고름 |
| 디스크를 무엇이 차지하나 | `size` | WizTree | 파이썬으로 훑음 |
| 똑같은 파일 | `dupes` | Czkawka CLI | 파이썬으로 비교 |
| 비슷한 사진 | `similar` | Czkawka CLI | 쓸 수 없음 |
| 빈 폴더·빈 파일 | `empty` | Czkawka CLI | 파이썬 |
| 사진 찍은 날짜·카메라·위치 | `exif` | ExifTool | 쓸 수 없음 |
| 압축 만들기·목록·검사·풀기 | `archive` | 7-Zip | .zip만 파이썬으로 |
| 폴더 복사 | `copy` | robocopy | 파이썬 |
| 폴더 정리 계획 → 이동 → 되돌리기 | `plan`, `move`, `undo` | 파이썬 | — |
| 휴지통으로 보내기 → 되돌리기 | `trash`, `undo` | 윈도 휴지통 | — |
| 무엇이 설치됐고 무엇이 되나, PC 사양 | `doctor` | — | — |
| 빠진 도구 한 번에 설치 (목록을 보고 확인한 뒤) | `setup` | winget / Chocolatey | 맥·리눅스는 명령 안내 |

Claude에게는 평소 말로 시키면 됩니다. 예: "작년에 받은 계약서 어디 있지?", "D 드라이브 뭐가 제일 큰지 봐 줘", "사진 폴더 중복 정리해 줘", "다운로드 폴더 종류별로 정리해 줘".

## 내용 찾기는 글자 먼저

글자를 뽑을 수 있는 파일은 색인 없이 글자부터 읽습니다. DigUp 색인은 글자가 없는 것(사진·스크린샷·스캔 PDF·소리·영상)에 씁니다.

- **이유**: DigUp 색인은 폴더의 모든 파일을 미리 처리합니다. PDF는 쪽마다 그림으로 바꿔 그림 모델을 거치므로, 큰 폴더는 첫 색인이 몇 시간에서 하루 넘게 걸리고 그래픽 카드도 오래 씁니다. 반면 글자로 된 문서는 글자만 읽어 문장 모델(EmbeddingGemma 2)에 넣으면 되어 훨씬 가볍습니다.
- **글자 먼저 찾기** (`search "..." --root 폴더`): txt·md·docx·hwpx·pptx·xlsx·odt·html·rtf와 프로그램으로 만든 PDF에서 글자를 바로 읽어 문단을 뜻으로 비교합니다. 처음 찾을 때 읽은 결과(숫자만, 글자는 저장 안 함)를 남겨 두므로 다음 찾기부터는 바뀐 파일만 읽습니다. 큰 폴더는 `--estimate`로 걸릴 시간을 먼저 봅니다.
- **DigUp 색인** (`index 폴더 --media-only`): 문서 글자는 빼고 사진·PDF·소리·영상만 색인합니다. 역시 `--estimate`로 시간을 먼저 봅니다.
- 옛 한글 파일(HWP)·DOC·XLS·PPT와 스캔 PDF는 글자로 읽지 못합니다. HWPX·DOCX로 저장하면 읽습니다.

## 안전장치

- `copy`·`move`·`trash`·`undo`는 **기본이 미리보기**입니다. `--execute`를 붙여야 실제로 바뀝니다. 스킬은 미리보기를 보여 주고 사용자 확인을 받은 뒤에만 실행하도록 되어 있습니다.
- 실행한 이동·삭제는 모두 **되돌리기 목록(CSV)** 에 남고, `undo`로 되돌립니다. 휴지통으로 보낸 것도 윈도 휴지통(리눅스는 홈 휴지통)에서 제자리로 돌려놓습니다.
- 삭제는 **휴지통으로만** 보냅니다. 휴지통이 없는 드라이브(네트워크·USB)는 거절합니다. 윈도가 영구 삭제하려 할 때(휴지통보다 큰 파일)는 화면에 확인 창이 뜹니다.
- 드라이브 맨 위, 사용자 폴더 자체, Windows·Program Files·ProgramData·AppData(임시 폴더 제외)는 옮기거나 지우지 않습니다.
- 복사는 아무것도 지우지 않고, 기본으로는 이미 있는 파일을 덮어쓰지 않습니다. 압축 풀기도 있는 파일을 건너뜁니다.

## 설치

### 1. 스킬 설치 (둘 중 하나)

**Claude Code 플러그인으로**

```
/plugin marketplace add hyunsungko/local-file-kit
/plugin install local-file-kit@local-file-kit
```

**직접 내려받아 스킬 폴더에 연결**

```powershell
git clone https://github.com/hyunsungko/local-file-kit.git
# Windows PowerShell (관리자 권한 필요 없음)
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\local-file-kit" -Target "<내려받은 폴더>\skills\local-file-kit"
```

```bash
# macOS / Linux
ln -s "<내려받은 폴더>/skills/local-file-kit" ~/.claude/skills/local-file-kit
```

필요한 것은 **Python 3.9 이상**뿐입니다(추가 패키지 없음). 윈도에서 `python`을 치면 Microsoft Store가 열리면 https://www.python.org/downloads/ 에서 설치하고 `py -3`으로 실행합니다.

### 2. 도구 설치 (필요한 것만)

모두 무료이고, 이 저장소는 실행 파일을 담지 않습니다. 각 도구의 공식 배포처에서 설치합니다.

한 번에 하려면 `setup`을 씁니다. 먼저 빠진 도구와 설치 명령·라이선스 주의를 보여 주기만 하고, 확인한 뒤에 `--yes`를 붙여야 설치합니다.

```
python <스킬 폴더>/scripts/lfk.py setup                      # 목록만 (아무것도 설치하지 않음)
python <스킬 폴더>/scripts/lfk.py setup --all --yes          # 빠진 것 전부 (WizTree 제외)
python <스킬 폴더>/scripts/lfk.py setup --tools everything,exiftool --yes   # 고른 것만
```

윈도에서는 winget(없으면 Chocolatey)으로 설치합니다. WizTree는 개인 사용만 무료라 `--all`에 들어가지 않고, 쓰려면 `--tools wiztree`로 직접 고릅니다. DigUp은 패키지 관리자에 없어 내려받을 주소만 알려 줍니다. 맥·리눅스는 brew·apt 명령을 보여 줍니다.

| 도구 | 하는 일 | 윈도 설치 | 비고 |
|---|---|---|---|
| Everything + ES | 이름 찾기 | `winget install voidtools.Everything` 그리고 `winget install voidtools.Everything.Cli` | Everything이 켜져 있어야 함 |
| DigUp | 내용·뜻 찾기 | https://github.com/ARahim3/DigUp/releases 에서 설치 후 한 번 실행(모델 약 865MB 내려받음) | 0.7.0-beta.1 사전 배포판 |
| WizTree | 용량 | `winget install AntibodySoftware.WizTree` | **개인 사용만 무료**, 업무용은 별도 라이선스 |
| Czkawka CLI | 중복·비슷한 사진·빈 폴더 | `winget install qarmin.czkawka.cli` | |
| ExifTool | 사진 정보 | `winget install OliverBetz.ExifTool` | |
| 7-Zip | 압축 | `winget install 7zip.7zip` | |
| robocopy | 복사 | 윈도에 들어 있음 | |

추천 최소 구성은 **Everything + DigUp** 입니다. 나머지는 없어도 대부분 파이썬으로 동작합니다.

### 3. 확인

```
python <스킬 폴더>/scripts/lfk.py doctor --pretty
```

찾은 도구와 버전, 기능별로 무엇을 쓰는지, 없는 도구의 설치 명령, 메모리·그래픽 카드·디스크가 나옵니다. 기본 위치가 아닌 곳에 설치했다면 환경 변수(`LFK_ES`, `LFK_DIGUP`, `LFK_WIZTREE`, `LFK_CZKAWKA`, `LFK_EXIFTOOL`, `LFK_7Z`, `LFK_ROBOCOPY`)나 설정 파일(`%APPDATA%\local-file-kit\config.json`의 `{"tools": {"7zip": "D:/Apps/7-Zip/7z.exe"}}`)로 알려 줍니다.

## 무엇을 실행하고, 무엇이 밖으로 나가나

- **실행하는 것**: 위 표의 도구 중 설치된 것, 윈도의 `tasklist`(DigUp 앱이 켜져 있는지 확인), `nvidia-smi`(있으면, 그래픽 메모리 확인), 맥의 `sysctl`(CPU·메모리 확인), 맥·리눅스에서 휴지통으로 보낼 때 `osascript`·`gio`. `setup --yes`를 쓸 때만 winget이나 Chocolatey를 실행해 도구를 설치합니다.
- **인터넷**: 이 스킬 자체는 인터넷에 접속하지 않습니다. `setup --yes`로 설치할 때 winget·Chocolatey가 내려받고, 모델은 DigUp 자신이 내려받습니다.
- **AI에게 보이는 것**: 찾기 결과의 파일 이름·경로·크기·날짜, `search`의 본문 발췌와 `--passages` 문단, `exif`의 촬영 정보(위치 포함). Claude를 쓰면 이 내용이 Anthropic으로 전송됩니다. 내용이 필요 없으면 `--no-excerpt`를 씁니다.
- **PC에 남는 것**: DigUp 색인(DigUp 앱 폴더, 본문 발췌 포함), 되돌리기 목록과 정리 계획(`%LOCALAPPDATA%\local-file-kit\`, 리눅스·맥은 `~/.local/state/local-file-kit/`).

## 사양과 지원 범위 (요약)

- **윈도 10/11 64비트**: 모든 기능. GitHub Actions의 새 윈도 러너(도구 없음·`setup`으로 도구 설치·DigUp 설치)에서 시험합니다. 윈도 10은 시험하지 못했습니다.
- **macOS·리눅스**: `find`·`size`·`copy`는 파이썬으로 동작(Everything·WizTree·robocopy는 윈도 전용). `dupes`·`similar`·`empty`·`exif`·`archive`는 각 도구를 설치하면 동작. DigUp은 맥(Apple Silicon, macOS 14+)과 리눅스(x64)판이 있으나 **이 스킬과 함께 시험하지 못했습니다**.
- 내용 찾기(DigUp)는 메모리 8GB 이상 권장. 그래픽 카드는 색인 속도만 바꾸고, 찾는 결과는 같습니다.
- 한국어 성능은 가짜 문서 42개와 질문 62개로 측정했습니다. 숫자와 한계는 [docs/SPECS.md](docs/SPECS.md)에 있습니다.

## 라이선스

MIT. 묶어 쓰는 도구는 각자의 라이선스를 따릅니다: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

## English

**local-file-kit** is a Claude Code skill (and plugin) that finds and organizes files on your own computer. It puts
one JSON command line, `lfk.py`, in front of free tools you may already have — Everything (names), DigUp with
EmbeddingGemma 2 (contents and meaning, Korean and English), WizTree (disk usage), Czkawka (duplicates, look-alike
photos, empty folders), ExifTool (photo metadata), 7-Zip (archives) and robocopy (copies) — and falls back to plain
Python, or tells you what to install, when one is missing.

**Text first.** `search "..." --root DIR` reads the text of txt, md, docx, hwpx, pptx, xlsx, odt, html, rtf and
program-made PDFs directly and ranks paragraphs by meaning with EmbeddingGemma 2 (the model inside DigUp), with no
index; paragraph vectors (numbers, not text) are cached so later searches only read changed files. DigUp's index,
which renders PDF pages and photos through its image model and is much heavier, is meant for what has no text:
photos, screenshots, scanned PDFs, audio and video (`index DIR --media-only`). Without DigUp, text search ranks by
shared words. Old binary HWP/DOC/XLS/PPT and scanned PDFs cannot be read as text.

**Install the skill**

```
/plugin marketplace add hyunsungko/local-file-kit
/plugin install local-file-kit@local-file-kit
```

or clone the repository and link `skills/local-file-kit` into `~/.claude/skills/` (Windows PowerShell:
`New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\local-file-kit" -Target "<clone>\skills\local-file-kit"`;
macOS/Linux: `ln -s`). Python 3.9+ is the only requirement. Then run `python <skill folder>/scripts/lfk.py doctor --pretty`.

**Install the tools you want** (Windows): `winget install voidtools.Everything` and `winget install voidtools.Everything.Cli`,
DigUp from https://github.com/ARahim3/DigUp/releases (open it once to fetch its 865 MB model),
`winget install AntibodySoftware.WizTree` (free for personal use only), `winget install qarmin.czkawka.cli`,
`winget install OliverBetz.ExifTool`, `winget install 7zip.7zip`. Everything + DigUp is the recommended minimum.
Or let the kit do it: `lfk.py setup` lists what is missing with the commands and licence notes and installs nothing;
`lfk.py setup --all --yes` (everything except WizTree) or `--tools everything,exiftool --yes` installs with winget, or
Chocolatey when winget is missing. On macOS/Linux `setup` prints the brew/apt commands.

**Safety.** `copy`, `move`, `trash` and `undo` only preview unless given `--execute`; the skill asks you before
executing. Every executed move or delete is logged to an undo CSV, and `undo` reverses it — including restoring
items from the Windows Recycle Bin or the Linux home Trash. Deletes go to the Recycle Bin only; drives without one
are refused. System folders, drive roots and the home folder itself are never moved or deleted. Copies never
delete and, by default, never overwrite.

**What runs and what leaves your PC.** The kit runs only the installed tools above plus `tasklist`,
`nvidia-smi`, `sysctl` (macOS specs), and `osascript`/`gio` for the Trash on macOS/Linux; only `setup --yes` runs
winget or Chocolatey, which download the tools. Otherwise it downloads nothing and makes no network connections. File names, paths, sizes, dates, text
excerpts (`search`) and photo metadata including GPS (`exif`) are shown to the AI model you use — with Claude, they
are sent to Anthropic. Use `--no-excerpt` to leave contents out. DigUp keeps its index (with text excerpts) on your
PC; undo logs and plans are kept in `%LOCALAPPDATA%\local-file-kit\` (or `~/.local/state/local-file-kit/`).

**Platforms.** Windows 10/11 x64: everything. macOS/Linux: `find`, `size` and `copy` run in Python; `dupes`,
`similar`, `empty`, `exif` and `archive` work once their tools are installed; DigUp exists for macOS and Linux but was
not tested with this kit. Measured speeds, hardware needs and the Korean search evaluation are in
[docs/SPECS.md](docs/SPECS.md); what was and was not tested is in [docs/TESTING.md](docs/TESTING.md).

MIT licence. The tools keep their own licences: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
