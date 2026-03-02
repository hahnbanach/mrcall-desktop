---
description: Read project's basic documentation (Architecture + Docs headers)
---
1. Read the file `./docs/README.md` to have an idea of what the project is
2. Read the file `./docs/ARCHITECTURE.md`. You should take the content of this file always in "memory". Always refer to it!
3. List recursively all markdown files (`*.md`) in the `docs/` directory 
4. For each file found in `docs/` (excluding ARCHITECTURE.md) and subdirs, read only the first 10 lines to extract the title/header using `head -n 10`.
5. Do not output anything more than `I read the documentation!`
