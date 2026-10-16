# 사양과 한계 / Requirements and limits

[English summary](#english-summary)

## 1. 한눈에 보기

| 항목 | 최소 | 권장 | 비고 |
|---|---|---|---|
| 운영체제 | Windows 10/11 64비트 | Windows 11 64비트 | GitHub Actions 윈도 러너에서 시험. Windows 10은 시험하지 못함 |
| 파이썬 | 3.9 | 3.11 이상 | 표준 라이브러리만 씀. GitHub Actions에서 3.9·3.12·3.13 시험 |
| CPU | x64 2코어 | 4코어 이상 | 이름 찾기·정리는 가벼움. 내용 찾기 색인은 CPU만 쓰면 느림 |
| 메모리 | 4GB (내용 찾기 없이) / 8GB (DigUp 사용) | 16GB 이상 | DigUp은 모델(865MB)을 메모리에 올림 |
| 그래픽 카드 | 없어도 됨 | Vulkan을 지원하고 그래픽 메모리가 1.5GB 이상 비어 있는 카드 | DigUp은 GPU가 더 빠를 때만 씀. 찾는 결과는 같음 |
| 디스크 | 스킬 1MB 미만 | SSD | DigUp 앱 약 200MB + 모델 865MB + 색인 |

내용 찾기(DigUp)를 빼면 거의 모든 PC에서 돕니다. 이름 찾기(Everything)와 용량(WizTree)은 윈도 전용이고, 없으면 파이썬이 폴더를 직접 훑습니다.

## 2. 기능별로 필요한 것

| 기능 | 필요한 것 | 없을 때 |
|---|---|---|
| `find` | Everything 실행 중 + es.exe | `--root` 폴더를 파이썬으로 훑음. 드라이브 전체는 수십 초 이상 |
| `search --root` (글자 먼저) | 없음. 뜻으로 고르려면 DigUp 앱의 모델(865MB) | 같은 낱말로 순위를 매김 |
| `search` (DigUp 색인)·`index`·`status` | DigUp 앱 + 모델(865MB) | 쓸 수 없음. `doctor`가 설치 방법을 알려 줌 |
| `search --passages` | DigUp 앱의 모델 | 글자 먼저 찾기에서는 같은 낱말로 고름 |
| `size` | WizTree | 파이썬으로 훑음 |
| `dupes`·`empty` | Czkawka CLI | 파이썬 (결과는 같고 느림) |
| `similar` | Czkawka CLI | 쓸 수 없음 |
| `exif` | ExifTool | 쓸 수 없음 |
| `archive` | 7-Zip | .zip만 파이썬으로 |
| `copy` | robocopy(윈도 기본) | 파이썬 shutil |
| `plan`·`move`·`trash`·`undo` | 없음 | — |

## 3. 글자 먼저, 색인은 글자 없는 것에

- DigUp 색인은 폴더의 파일을 모두 미리 처리합니다. PDF는 쪽마다 그림으로 바꿔 그림 모델을 거치고, 사진·스크린샷도 그림 모델을 거칩니다. 그래서 자료가 많으면 첫 색인이 오래 걸리고 그 동안 CPU·그래픽 카드를 계속 씁니다.
- 글자로 된 문서는 글자만 읽어 문장 모델에 넣으면 됩니다. `search --root`는 찾을 때 그 폴더만 읽고, 읽은 결과(문단마다 숫자 768개, 글자는 저장 안 함)를 파일별로 남겨 다음에는 바뀐 파일만 읽습니다.
- 그래서 권하는 순서는 이렇습니다.
  1. 문서는 `search "..." --root 폴더`. 처음이고 폴더가 크면 `--estimate`로 시간을 먼저 봅니다.
  2. 사진·스크린샷·스캔 PDF·소리·영상을 뜻으로 찾아야 할 때만 `index 폴더 --media-only --estimate`로 시간을 보고 색인합니다.
- 아래 4절에 같은 가짜 자료를 두 방식으로 처리한 시간이 있습니다.

## 4. 실측 (GitHub Actions 러너)

모든 숫자는 GitHub Actions의 `windows-latest` 러너(Windows Server 2025, 가상 CPU 4개, 메모리 16GB, **그래픽 카드 없음**)에서 측정했습니다.
자료는 이 저장소의 생성기로 만든 가짜 자료입니다. 측정은 [워크플로](../.github/workflows/test.yml)가 매번 다시 합니다.

| 작업 | 결과 |
|---|---|
| DigUp 색인, 가짜 문서 42개 (CPU) | 15.3초 (프로그램과 모델 시작 포함) |
| DigUp 색인, 가짜 한글 텍스트 문서 300개·0.4MB (CPU) | 417초, 분당 43개, 색인 2.1MB |
| DigUp 찾기 1번 | 약 1.2초 (매번 프로그램을 새로 띄움) |
| `--passages`의 문단 숫자 바꾸기 (CPU) | 초당 약 9.5문단 |
| 이름 찾기 1번, 러너의 Program Files 약 29만 항목 | Everything 0.24초 / 파이썬 훑기 4.0초 |
| 용량, 같은 폴더 약 26.6만 파일·65GB | 파이썬 훑기 105초 (WizTree는 Actions에 설치하지 않음) |
| 중복 찾기(100KB 이상), 같은 폴더 3,617묶음 | Czkawka 232초 / 파이썬 131초 (결과 같음) |

- 이 러너에서는 중복 찾기가 파이썬 쪽이 더 빨랐습니다. 파이썬은 같은 크기 파일의 앞 64KB를 먼저 비교해 다른 파일을 빨리 걸러 냅니다. 디스크와 파일 구성에 따라 결과는 달라질 수 있습니다.

- 그래픽 카드가 있으면 색인이 빨라집니다. 얼마나 빨라지는지는 카드, 비어 있는 그래픽 메모리, 자료 종류(문서·사진·스크린샷·PDF)에 따라 다릅니다.
- 첫 색인 시간은 `index 폴더 --estimate`로 미리 볼 수 있습니다.

## 5. 한국어 성능 (EmbeddingGemma 2, DigUp 0.7.0-beta.1 공식판)

가짜 한국어 문서 36개와 영어 문서 6개를 만들고, 질문 62개로 맞는 문서가 몇 위에 나오는지 측정했습니다.
비슷한 주제를 일부러 섞었습니다(전세·월세, 고양이·강아지, 노트북·휴대전화, 적금·주식 배당 등).
자료와 질문은 [tests/korean_eval_data.py](../tests/korean_eval_data.py)에 있고, 실행은 `python tests/eval_korean.py <빈 폴더>`입니다.
질문별 결과는 Actions 실행의 `korean-eval` 결과 파일로 남습니다. 아래 숫자는 그래픽 카드 없는 Actions 러너의 값입니다.

| 질문 종류 | 개수 | 1위 정답 | 3위 안 | MRR | 기본 설정에서 보임 | 단어 일치만으로 1위 |
|---|---|---|---|---|---|---|
| 한국어, 문서와 다른 낱말로 바꿔 말함 | 36 | 97.2% | 100% | 0.986 | 97.2% | 52.8% |
| 한국어, 문서의 핵심 낱말 그대로 | 8 | 100% | 100% | 1.000 | 100% | 100% |
| 한국어 구어체·띄어쓰기 없음·줄임말 | 6 | 83.3% | 83.3% | 0.854 | 83.3% | 16.7% |
| 한국어 질문 → 영어 문서 | 6 | 100% | 100% | 1.000 | 100% | 0% |
| 영어 질문 → 한국어 문서 | 6 | 100% | 100% | 1.000 | 100% | 0% |
| **전체** | **62** | **96.8%** | **98.4%** | **0.978** | | |

- 틀린 2개
  - "세 들어 살 때 매달 내는 공용 비용에 뭐가 들어가는지" → 가계부 문서가 1위, 정답(월세 관리비)은 2위. 1위가 뚜렷해서 정답은 기본 설정에서 숨었습니다.
  - "와파 개느림"(와이파이 줄임말 + 비속어) → 정답 8위.
- 파일 안에서 맞는 문단 고르기(`--passages`): 12개 중 11개(91.7%). 틀린 1개는 "카드 사용액 공제는 얼마부터"에 다른 공제 문단을 고른 경우입니다.
- "기본 설정에서 보임"은 DigUp이 약한 결과를 숨기는 문턱(z 2.0)을 넘은 비율입니다. 정답이 1위가 아니면 숨는 경우가 많습니다.
- "단어 일치만으로 1위"는 질문 낱말이 문서에 들어 있는 수로 순위를 매긴 비교 기준입니다. 바꿔 말한 질문과 언어가 다른 질문에서 뜻 찾기의 이점이 큽니다.
- 그래픽 카드가 있어도 결과는 같고 속도만 다릅니다.

한계
- 문서 42개짜리 작은 색인입니다. 수십만 개를 색인하면 비슷한 문서가 많아져 순위가 떨어질 수 있습니다.
- 질문과 문서를 같은 사람이 만들었습니다. 실제 사용자의 말투와 다를 수 있습니다.
- 한국어 PDF, 스캔 문서, HWP는 이 시험에 넣지 않았습니다. 공식판 DigUp은 HWP·엑셀을 읽지 않습니다.
- 줄임말·비속어에는 약합니다. 정식 낱말로 다시 찾으면 됩니다.

## 6. 그래픽 카드가 없거나 작을 때

- **찾는 결과는 같습니다.** 위 한국어 시험은 그래픽 카드 없이 돌린 값입니다.
- **색인이 느려집니다.** 사진·스크린샷·스캔 PDF가 많으면 첫 색인이 몇 시간에서 하루 이상 걸릴 수 있으니 `--estimate`로 먼저 확인합니다.
- **찾기는 거의 같습니다.** DigUp이 질의를 CPU로 바꾸기 때문입니다.
- 다른 GPU 프로그램(음성·영상 생성, 게임 등)과 함께 돌려 그래픽 메모리가 모자라면 DigUp이 공유 메모리를 써서 크게 느려질 수 있습니다. 그래픽 메모리가 풀려도 **DigUp 앱을 다시 켜야** 빨라집니다. `doctor`는 그래픽 메모리 여유가 1.5GB 아래면 알려 줍니다(NVIDIA 카드에서만 사용량을 읽을 수 있음).
- CPU만 쓰게 하려면 `--cpu`(= `DIGUP_DEVICE=cpu`).

## 7. 도구별 한계

| 도구 | 한계 |
|---|---|
| Everything | 로컬 NTFS·ReFS 드라이브만 자동 색인. 네트워크·FAT·exFAT·USB·클라우드 드라이브(구글 드라이브 등)는 Everything 설정의 '폴더'에 따로 넣어야 함. 이 스킬은 Everything이 모르는 폴더를 알아채면 파이썬으로 훑음. Everything이 켜져 있어야 함. 파일 내용은 모름 |
| DigUp | 색인한 폴더만 찾음. 파일마다 가장 맞는 곳 하나만 냄(그래서 `--passages`를 더함). 긴 PDF의 정확한 쪽, 긴 영상의 정확한 시각은 약함. 경로 260자 이상은 읽지 못함. 클라우드 전용 파일(내려받지 않은 OneDrive 파일 등)·연결 지점은 건너뜀. 공식판이 읽는 문서: txt·md·rtf·docx·odt·html·PDF(그림·소리·영상 별도). HWP·엑셀은 읽지 않음. helper CLI는 공개 문서가 없는 내부 도구라 판이 바뀌면 명령이 바뀔 수 있음(`doctor`가 필요한 명령이 있는지 확인). 색인 DB에 글 발췌가 저장됨(PC 밖으로 나가지 않음) |
| 글자 먼저 (PDF 읽기) | 프로그램으로 만든 PDF만 글자를 읽음. 스캔 PDF는 '글자 없음'으로 알려 줌. 암호 걸린 PDF는 건너뜀. 여러 단 짜기·표는 읽는 순서가 섞일 수 있고, 줄이 바뀌는 곳의 띄어쓰기가 빠질 수 있음 |
| 글자 먼저 (그 밖) | 옛 HWP·DOC·XLS·PPT는 읽지 못함(HWPX·DOCX·XLSX·PPTX로 저장하면 읽음). 클라우드 전용 파일은 내려받지 않으려고 건너뜀. 한 번에 `--max-files`(기본 2만)개까지, 새로 읽는 시간은 `--max-seconds`(기본 300초)까지 |
| WizTree | 개인 사용만 무료, 업무용은 별도 라이선스. 관리자 없이 부르므로 빠른 MFT 읽기는 쓰지 않음. 파이썬이 읽지 못하는 시스템 폴더까지 세므로 합계가 파이썬 훑기보다 클 수 있음 |
| Czkawka | 비슷한 사진의 기본 설정(Gradient, 16, 5)은 엄격해서 밝기만 바꾼 사진도 못 찾을 수 있음 → `--hash-alg Mean --hash-size 8 --max-difference 10`. 동영상 비교는 ffmpeg가 필요해 이 스킬에 넣지 않음. 윈도는 x64만. 하드 링크는 중복으로 세지 않음(파이썬 대체도 같음) |
| ExifTool | 한글·공백 파일 이름은 UTF-8 인자 파일로 넘겨 해결(시험함) |
| 7-Zip | 압축 풀 때 있는 파일은 건너뜀. 암호 압축은 다루지 않음 |
| robocopy | 미리보기 목록의 상태 낱말이 윈도 언어에 따라 바뀌어 크기와 경로만 읽음. 오류 줄은 영어·한국어 문구만 알아봄 |
| 휴지통 | 휴지통이 없는 드라이브(네트워크·USB)는 거절. 휴지통보다 큰 파일은 윈도가 확인 창을 띄움. 윈도 경로 260자 이상은 휴지통 API가 실패할 수 있음(시험 안 함) |

## 8. macOS·리눅스

| 기능 | 리눅스 | macOS |
|---|---|---|
| `find`, `size`, `copy` | 파이썬으로 동작, GitHub Actions Ubuntu에서 시험 통과 | 파이썬으로 동작, GitHub Actions macOS에서 시험 통과 |
| `dupes`, `empty` | 파이썬 동작. Czkawka를 깔면 그것을 씀(Actions에서 시험 통과) | 파이썬 동작, 시험 통과. Czkawka 사용은 시험 못 함 |
| `similar`, `exif`, `archive`(7z) | 도구를 깔면 동작(`apt install libimage-exiftool-perl 7zip`), Actions에서 시험 통과 | 시험 못 함 |
| `trash`, `undo` | `gio trash`로 홈 휴지통에 보내고 되돌리기까지 동작 | Finder 휴지통으로 보냄(시험 못 함). 되돌리기는 Finder에서 직접 |
| `search`, `index` | DigUp 리눅스판(x64 .deb·AppImage)이 있으나 **이 스킬과 함께 시험 못 함** | DigUp 맥판(Apple Silicon, macOS 14+)이 있으나 **시험 못 함** |
| Everything, WizTree, robocopy | 없음(윈도 전용) | 없음 |

---

## English summary

- **Runs on** Windows 10/11 x64 (tested on GitHub Actions Windows runners; not on Windows 10), Python 3.9+, no extra
  packages. Meaning search needs DigUp (about 200 MB app + 865 MB model); 8 GB of RAM is recommended. A Vulkan GPU
  with 1.5 GB of free memory speeds up indexing but does not change results.
- **Measured** on a GitHub Actions `windows-latest` runner (4 vCPUs, 16 GB, no GPU): DigUp indexed 42 made-up
  documents in 15.3 s and 300 small Korean text files in 417 s (43 a minute), a search takes about 1.2 s, and
  `--passages` embeds about 9.5 paragraphs a second on the CPU. On the runner's Program Files (about 290,000
  entries) Everything answers a name query in 0.24 s versus 4.0 s for a Python walk.
- **Korean quality** (42 made-up documents, 62 queries, same runner): the right file is first for 96.8% of queries and
  in the top 3 for 98.4% (MRR 0.978); paraphrased Korean 97.2%, slang/no-spacing 83.3%, Korean↔English 100%. Picking
  the right paragraph inside a file: 11 of 12. Small index, self-written queries, no Korean PDFs/HWP: treat as an
  indication, not a guarantee.
- **Limits**: Everything indexes local NTFS/ReFS only; DigUp returns one spot per file, skips paths over 260 characters
  and cloud-only files, and its official build does not read HWP or Excel; WizTree is free for personal use only.
- **macOS/Linux**: Python features tested on GitHub Actions Ubuntu and macOS; macOS Trash, macOS tools and DigUp on
  macOS/Linux not tested.
