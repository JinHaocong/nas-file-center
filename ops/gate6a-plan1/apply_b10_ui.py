from pathlib import Path

path = Path("frontend/src/pages/Quarantine/index.tsx")
source = path.read_text()
old = '''          <Tooltip
            title={
              !isAdmin
                ? '仅系统管理员允许批量永久删除'
                : isSafeMode
                ? 'ALLOW_MUTATION=false，禁止生成批量永久删除计划'
                : !allowDelete
                ? 'ALLOW_DELETE=false，禁止永久删除'
                : undefined
            }
          >
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={selectedEntryIds.length === 0 || !isAdmin || isSafeMode || !allowDelete}
              onClick={() => {
                setBulkPurgeEntryIds([...selectedEntryIds]);
                setBulkPurgeOpen(true);
              }}
            >
              批量永久删除
            </Button>
          </Tooltip>
'''
new = '''          <Tooltip title="批量永久删除在 v0.3.6 已暂缓：当前无法安全证明 hard-link ownership scope，后端将 fail-closed">
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={true}
            >
              批量永久删除
            </Button>
          </Tooltip>
'''
assert source.count(old) == 1, f"expected one bulk purge toolbar block, got {source.count(old)}"
path.write_text(source.replace(old, new))
