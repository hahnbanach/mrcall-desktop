npx claude-flow@alpha swarm "$(cat <<'EOF'
MISSION: Consolidate and organize ALL Zylch documentation - MAKE ACTUAL CHANGES

CONTEXT:
Documentation has ballooned to 100s of .md files. Need to:
1. Inventory all .md files across codebases
2. Identify duplicates, outdated, contradictory docs
3. Reorganize into clear structure
4. Move outdated docs to ~/hb/zylch/docs/OLD/
5. CREATE master index

CODEBASES:
- ~/hb/zylch (main backend)
- ~/hb/zylch/frontend (frontend)
- ~/hb/zylch-cli (CLI)

TARGET STRUCTURE:
```
~/hb/zylch/docs/
├── architecture/     # High-level design
├── api/             # API documentation
├── guides/          # User guides
├── development/     # Dev setup
├── integration/     # Integration docs
├── OLD/             # Outdated docs (move here)
└── INDEX.md         # Master index (CREATE THIS)
```

TASKS (ACTUALLY MOVE/CREATE FILES):

TASK 1 - Inventory & Categorize
Find all .md files, categorize by:
- Current vs outdated
- Duplicate vs unique
- Topic (architecture, API, guides, etc.)

CREATE: ~/hb/zylch/docs/DOC_INVENTORY.md
Store: memory key 'doc_inventory'

TASK 2 - Move Outdated Docs
Identify outdated docs (refers to deleted code, contradicted by newer docs, superseded)
ACTUALLY MOVE files to ~/hb/zylch/docs/OLD/
```bash
mkdir -p ~/hb/zylch/docs/OLD
mv [outdated-file.md] ~/hb/zylch/docs/OLD/
```
Store: memory key 'moved_outdated'

TASK 3 - Reorganize Current Docs
ACTUALLY MOVE current docs into proper structure:
```bash
mkdir -p ~/hb/zylch/docs/{architecture,api,guides,development,integration}
mv [architecture-doc.md] ~/hb/zylch/docs/architecture/
mv [api-doc.md] ~/hb/zylch/docs/api/
# etc
```
Store: memory key 'reorganized_docs'

TASK 4 - Merge Duplicates
Find duplicate/redundant docs
ACTUALLY CONSOLIDATE into single files
DELETE true duplicates
Store: memory key 'merged_docs'

TASK 5 - Create Master Index
Wait for: doc_inventory, moved_outdated, reorganized_docs, merged_docs

CREATE: ~/hb/zylch/docs/INDEX.md
Contents:
- Overview of all documentation
- What each doc covers
- Recommended reading order
- What was moved to OLD/ (with reasons)
- Quick reference guide

COORDINATION:
- Use memory_store to share findings
- Don't move same file twice
- Preserve all content (move to OLD/, don't delete unless true duplicate)

MAKE ACTUAL FILE OPERATIONS - not just documentation plans!
EOF
)" --agents 5 --strategy development --monitor