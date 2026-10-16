# Third-party tools / 제3자 도구 고지

local-file-kit contains **no third-party code or executables**. It runs tools that you install yourself,
from wherever they are installed. Each tool keeps its own licence; installing and using it is between you and its
author. 이 저장소에는 다른 사람의 코드나 실행 파일이 들어 있지 않습니다. 각자 설치한 도구를 불러 쓸 뿐이며,
도구마다 라이선스가 따로 있습니다.

| Tool | Licence | Official source | Notes |
|---|---|---|---|
| Everything / ES (es.exe) | MIT | https://www.voidtools.com/downloads/ · https://github.com/voidtools/ES | Windows only |
| DigUp | MIT | https://github.com/ARahim3/DigUp/releases | Its helper CLI is called as installed; it is not a documented public interface and may change |
| EmbeddingGemma 2 (model used by DigUp) | Apache-2.0 | https://huggingface.co/google/embeddinggemma-2 · https://huggingface.co/ggml-org/embeddinggemma-2-GGUF | Downloaded by DigUp, not by this kit |
| WizTree | Proprietary freeware | https://diskanalyzer.com/download | **Free for personal use only.** Business use needs a supporter code per business location; organisations over 100 people need an Enterprise licence (see WizTree's EULA) |
| Czkawka CLI | MIT (the Krokiet GUI is GPL-3.0; not used) | https://github.com/qarmin/czkawka/releases | x64 on Windows |
| ExifTool | Perl licence (GPL-1.0+ or Artistic) | https://exiftool.org/ | |
| 7-Zip | LGPL-2.1+ (parts BSD; unRAR restriction) | https://www.7-zip.org/ | |
| Robocopy | Part of Windows | https://learn.microsoft.com/windows-server/administration/windows-commands/robocopy | |

Optional Python package used for testing only: Pillow (MIT-CMU, https://python-pillow.org/), to draw sample photos.
Optional on macOS/Linux: send2trash (BSD-3-Clause) for the Trash, if installed.
