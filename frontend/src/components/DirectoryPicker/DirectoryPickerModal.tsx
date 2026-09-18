import React, { useState, useEffect, useMemo } from 'react';
import {
  Modal,
  Button,
  Input,
  List,
  Checkbox,
  Tag,
  Space,
  Spin,
  Alert,
  Empty,
  Typography,
  Tooltip,
  Tabs,
  message,
  Popconfirm,
  Pagination,
} from 'antd';
import {
  FolderOutlined,
  FolderOpenOutlined,
  ArrowUpOutlined,
  ReloadOutlined,
  StarOutlined,
  StarFilled,
  HistoryOutlined,
  SearchOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { filesystemApi } from '../../api/filesystem';
import { DirectoryPickerModalProps } from './types';
import { PathBreadcrumb } from './PathBreadcrumb';
import { formatDateTime } from '../../utils/format';
import { useResponsive } from '../../hooks/useResponsive';

const { Text } = Typography;

export const DirectoryPickerModal: React.FC<DirectoryPickerModalProps> = ({
  open,
  onCancel,
  onConfirm,
  multiple = false,
  initialPath,
  selectedValues,
}) => {
  const queryClient = useQueryClient();
  const { isMobile } = useResponsive();

  const [currentPath, setCurrentPath] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [page, setPage] = useState<number>(1);
  const pageSize = 100;
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [favoriteLabel, setFavoriteLabel] = useState<string>('');
  const [isAddingFavorite, setIsAddingFavorite] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<string>('browser');

  // Initialize currentPath and selections when modal opens
  useEffect(() => {
    if (open) {
      if (initialPath && initialPath.trim()) {
        setCurrentPath(initialPath.trim());
      } else if (selectedValues) {
        const first = Array.isArray(selectedValues) ? selectedValues[0] : selectedValues;
        if (first && first.trim()) {
          setCurrentPath(first.trim());
        } else {
          setCurrentPath('');
        }
      } else {
        setCurrentPath('');
      }

      if (multiple) {
        if (Array.isArray(selectedValues)) {
          setSelectedPaths(selectedValues.filter(Boolean));
        } else if (typeof selectedValues === 'string' && selectedValues.trim()) {
          setSelectedPaths([selectedValues.trim()]);
        } else {
          setSelectedPaths([]);
        }
      } else {
        if (typeof selectedValues === 'string' && selectedValues.trim()) {
          setSelectedPaths([selectedValues.trim()]);
        } else if (Array.isArray(selectedValues) && selectedValues.length > 0) {
          setSelectedPaths([selectedValues[0]]);
        } else {
          setSelectedPaths([]);
        }
      }
      setSearchQuery('');
      setPage(1);
      setIsAddingFavorite(false);
      setActiveTab('browser');
    }
  }, [open, initialPath, selectedValues, multiple]);

  // Query directory list for currentPath (or default root if currentPath is empty)
  const {
    data: dirData,
    isLoading: isDirLoading,
    error: dirError,
    refetch: refetchDir,
  } = useQuery({
    queryKey: ['filesystem', 'list', currentPath, page, pageSize, searchQuery],
    queryFn: () =>
      filesystemApi.listDirectory(
        currentPath || undefined,
        true,
        page,
        pageSize,
        searchQuery || undefined,
      ),
    enabled: open,
    staleTime: 5000,
  });

  // Sync actual currentPath when backend resolves default allowed root
  useEffect(() => {
    if (dirData?.path && !currentPath) {
      setCurrentPath(dirData.path);
    }
  }, [dirData?.path, currentPath]);

  // Query favorites
  const { data: favData } = useQuery({
    queryKey: ['filesystem', 'favorites'],
    queryFn: () => filesystemApi.listFavorites(),
    enabled: open,
    staleTime: 10000,
  });

  // Query recent paths
  const { data: recentData } = useQuery({
    queryKey: ['filesystem', 'recent'],
    queryFn: () => filesystemApi.listRecent(20),
    enabled: open,
    staleTime: 10000,
  });

  // Add favorite mutation
  const addFavMutation = useMutation({
    mutationFn: ({ path, label }: { path: string; label?: string }) =>
      filesystemApi.addFavorite(path, label),
    onSuccess: () => {
      message.success('已添加到收藏');
      setIsAddingFavorite(false);
      setFavoriteLabel('');
      queryClient.invalidateQueries({ queryKey: ['filesystem', 'favorites'] });
    },
    onError: (err: any) => {
      message.error(err.message || '添加收藏失败');
    },
  });

  // Delete favorite mutation
  const delFavMutation = useMutation({
    mutationFn: (id: number) => filesystemApi.deleteFavorite(id),
    onSuccess: () => {
      message.success('已删除收藏');
      queryClient.invalidateQueries({ queryKey: ['filesystem', 'favorites'] });
    },
    onError: (err: any) => {
      message.error(err.message || '删除收藏失败');
    },
  });

  const effectiveCurrentPath = currentPath || dirData?.path || '';

  const isCurrentFavorite = useMemo(() => {
    return favData?.items?.some((f) => f.path === effectiveCurrentPath);
  }, [favData?.items, effectiveCurrentPath]);

  // Handle navigating to path
  const handleNavigate = (path: string) => {
    setCurrentPath(path);
    setSearchQuery('');
    setPage(1);
    setActiveTab('browser');
  };

  // Toggle selection
  const handleToggleSelect = (path: string) => {
    if (multiple) {
      if (selectedPaths.includes(path)) {
        setSelectedPaths(selectedPaths.filter((p) => p !== path));
      } else {
        setSelectedPaths([...selectedPaths, path]);
      }
    } else {
      setSelectedPaths([path]);
    }
  };

  // Select current path
  const handleSelectCurrent = () => {
    if (!effectiveCurrentPath) return;
    if (multiple) {
      if (!selectedPaths.includes(effectiveCurrentPath)) {
        setSelectedPaths([...selectedPaths, effectiveCurrentPath]);
        message.success(`已添加：${effectiveCurrentPath}`);
      }
    } else {
      setSelectedPaths([effectiveCurrentPath]);
    }
  };

  // Confirm selection
  const handleConfirm = async () => {
    if (multiple) {
      if (selectedPaths.length === 0) {
        if (effectiveCurrentPath) {
          const result = [effectiveCurrentPath];
          await filesystemApi.recordRecent(result).catch(() => {});
          onConfirm(result);
        }
      } else {
        await filesystemApi.recordRecent(selectedPaths).catch(() => {});
        onConfirm(selectedPaths);
      }
    } else {
      const result = selectedPaths.length > 0 ? selectedPaths[0] : effectiveCurrentPath;
      if (result) {
        await filesystemApi.recordRecent([result]).catch(() => {});
        onConfirm(result);
      }
    }
    onCancel();
  };

  return (
    <Modal
      title={
        <div className="nfc-directory-picker-title">
          <FolderOpenOutlined className="nfc-directory-picker-title-icon" />
          <span>选择目录 ({multiple ? '多选' : '单选'})</span>
        </div>
      }
      open={open}
      onCancel={onCancel}
      className="nfc-directory-picker-modal nfc-overlay-modal"
      width={isMobile ? 'calc(100vw - 16px)' : 760}
      destroyOnClose
      footer={
        <div className="nfc-directory-picker-footer">
          <div className="nfc-directory-picker-selection">
            {multiple ? (
              <div>
                <Text type="secondary" className="nfc-directory-picker-selection-count">
                  已选 <Text strong>{selectedPaths.length}</Text> 个目录
                </Text>
                {selectedPaths.length > 0 && (
                  <div className="nfc-directory-picker-selected-tags">
                    {selectedPaths.map((p) => (
                      <Tag
                        key={p}
                        closable
                        onClose={() => setSelectedPaths(selectedPaths.filter((item) => item !== p))}
                        className="nfc-directory-picker-selected-tag"
                      >
                        {p}
                      </Tag>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <Text ellipsis className="nfc-directory-picker-current-selection">
                当前选择：
                <Text strong code>
                  {selectedPaths.length > 0 ? selectedPaths[0] : effectiveCurrentPath}
                </Text>
              </Text>
            )}
          </div>
          <Space className="nfc-directory-picker-footer-actions">
            <Button onClick={onCancel}>取消</Button>
            <Button
              type="primary"
              onClick={handleConfirm}
              icon={<CheckCircleOutlined />}
              disabled={!effectiveCurrentPath && selectedPaths.length === 0}
            >
              确认选择
            </Button>
          </Space>
        </div>
      }
    >
      <div className="nfc-directory-picker-body">
        {/* Navigation Bar */}
        <div className="nfc-directory-browser-toolbar">
          <div className="nfc-directory-browser-row">
            <PathBreadcrumb
              currentPath={effectiveCurrentPath}
              allowedRoots={dirData?.allowed_roots || []}
              onNavigate={handleNavigate}
            />
            <Space size="small">
              <Tooltip title="返回上一级">
                <Button
                  size="small"
                  icon={<ArrowUpOutlined />}
                  disabled={!dirData?.parent}
                  onClick={() => dirData?.parent && handleNavigate(dirData.parent)}
                />
              </Tooltip>
              <Tooltip title="刷新目录">
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={isDirLoading}
                  onClick={() => refetchDir()}
                />
              </Tooltip>
              <Tooltip title={isCurrentFavorite ? '已收藏' : '收藏当前目录'}>
                <Button
                  size="small"
                  icon={isCurrentFavorite ? <StarFilled className="nfc-favorite-active-icon" /> : <StarOutlined />}
                  disabled={!effectiveCurrentPath}
                  onClick={() => setIsAddingFavorite(!isAddingFavorite)}
                />
              </Tooltip>
              <Button
                size="small"
                type="dashed"
                icon={<PlusOutlined />}
                disabled={!effectiveCurrentPath}
                onClick={handleSelectCurrent}
              >
                选择当前目录
              </Button>
            </Space>
          </div>

          {isAddingFavorite && effectiveCurrentPath && (
            <div className="nfc-directory-favorite-editor">
              <Input
                size="small"
                placeholder="收藏别名 (可选，如：影视库)"
                value={favoriteLabel}
                onChange={(e) => setFavoriteLabel(e.target.value)}
                className="nfc-directory-favorite-input"
              />
              <Button
                size="small"
                type="primary"
                loading={addFavMutation.isPending}
                onClick={() =>
                  addFavMutation.mutate({ path: effectiveCurrentPath, label: favoriteLabel })
                }
              >
                保存收藏
              </Button>
              <Button size="small" onClick={() => setIsAddingFavorite(false)}>
                取消
              </Button>
            </div>
          )}
        </div>

        {/* Tabs for Browser, Favorites, Recent */}
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          size="small"
          items={[
            {
              key: 'browser',
              label: (
                <span>
                  <FolderOutlined /> 目录浏览
                </span>
              ),
              children: (
                <div>
                  <div className="nfc-directory-search-row">
                    <Input
                      size="small"
                      placeholder="搜索子目录 (如: Download, Photos)..."
                      prefix={<SearchOutlined className="nfc-directory-search-icon" />}
                      value={searchQuery}
                      onChange={(e) => {
                        setSearchQuery(e.target.value);
                        setPage(1);
                      }}
                      allowClear
                    />
                  </div>

                  {dirError ? (
                    <Alert
                      type="error"
                      showIcon
                      message="无法读取目录"
                      description={(dirError as any)?.message || '请确认目录是否存在且具备容器内访问权限'}
                      action={
                        <Button size="small" onClick={() => refetchDir()}>
                          重试
                        </Button>
                      }
                      className="nfc-directory-error"
                    />
                  ) : isDirLoading ? (
                    <div className="nfc-directory-loading">
                      <Spin tip="加载目录中..." />
                    </div>
                  ) : !dirData?.items || dirData.items.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        searchQuery
                          ? '未匹配到包含关键词的子目录'
                          : '当前目录下无子文件夹'
                      }
                    />
                  ) : (
                    <div>
                      <div className="nfc-directory-list-viewport">
                        <List
                          size="small"
                          dataSource={dirData.items}
                          renderItem={(item) => {
                            const isSelected = selectedPaths.includes(item.path);
                            return (
                              <List.Item
                                className={isSelected ? 'nfc-directory-item is-selected' : 'nfc-directory-item'}
                                actions={[
                                  multiple ? (
                                    <div
                                      key="chk"
                                      onClick={(e) => e.stopPropagation()}
                                      className="nfc-directory-item-checkbox"
                                    >
                                      <Checkbox
                                        checked={isSelected}
                                        onClick={(e) => e.stopPropagation()}
                                        onChange={() => handleToggleSelect(item.path)}
                                      />
                                    </div>
                                  ) : (
                                    <Button
                                      key="sel"
                                      size="small"
                                      type={isSelected ? 'primary' : 'default'}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setSelectedPaths([item.path]);
                                      }}
                                    >
                                      {isSelected ? '已选' : '选择'}
                                    </Button>
                                  ),
                                ]}
                                onClick={() => handleNavigate(item.path)}
                              >
                                <List.Item.Meta
                                  avatar={
                                    <FolderOutlined
                                      className={isSelected ? 'nfc-directory-item-icon is-selected' : 'nfc-directory-item-icon'}
                                    />
                                  }
                                  title={
                                    <Text strong={isSelected} className="nfc-directory-item-name">
                                      {item.name}
                                    </Text>
                                  }
                                  description={
                                    <Text type="secondary" className="nfc-directory-item-path">
                                      {item.path}
                                    </Text>
                                  }
                                />
                              </List.Item>
                            );
                          }}
                        />
                      </div>

                      {/* Pagination Bar */}
                      <div className="nfc-directory-pagination-row">
                        <Text type="secondary" className="nfc-directory-pagination-count">
                          共 {dirData.total} 个目录
                        </Text>
                        {dirData.total > pageSize && (
                          <Pagination
                            size="small"
                            current={page}
                            pageSize={pageSize}
                            total={dirData.total}
                            onChange={(newPage) => setPage(newPage)}
                            showSizeChanger={false}
                          />
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ),
            },
            {
              key: 'favorites',
              label: (
                <span>
                  <StarOutlined /> 收藏目录 ({favData?.items?.length || 0})
                </span>
              ),
              children: (
                <div className="nfc-directory-secondary-list">
                  {!favData?.items || favData.items.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="暂无收藏目录，点击上方 ⭐ 可快速收藏"
                    />
                  ) : (
                    <List
                      size="small"
                      dataSource={favData.items}
                      renderItem={(fav) => (
                        <List.Item
                          className={fav.exists ? 'nfc-directory-secondary-item' : 'nfc-directory-secondary-item is-missing'}
                          actions={[
                            <Button
                              key="jump"
                              size="small"
                              type="link"
                              disabled={!fav.exists}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleNavigate(fav.path);
                              }}
                            >
                              进入目录
                            </Button>,
                            <div
                              key="del"
                              onClick={(e) => e.stopPropagation()}
                              className="nfc-directory-item-checkbox"
                            >
                              <Popconfirm
                                title="确认删除该收藏？"
                                onConfirm={() => delFavMutation.mutate(fav.id)}
                              >
                                <Button
                                  size="small"
                                  type="text"
                                  danger
                                  icon={<DeleteOutlined />}
                                  onClick={(e) => e.stopPropagation()}
                                />
                              </Popconfirm>
                            </div>,
                          ]}
                          onClick={() => fav.exists && handleNavigate(fav.path)}
                        >
                          <List.Item.Meta
                            avatar={
                              <StarFilled
                                className={fav.exists ? 'nfc-directory-favorite-icon' : 'nfc-directory-favorite-icon is-disabled'}
                              />
                            }
                            title={
                              <Space>
                                <Text strong>{fav.label || fav.path}</Text>
                                {!fav.exists && <Tag color="error">路径不存在</Tag>}
                              </Space>
                            }
                            description={
                              <Text type="secondary" className="nfc-directory-item-path">
                                {fav.path}
                              </Text>
                            }
                          />
                        </List.Item>
                      )}
                    />
                  )}
                </div>
              ),
            },
            {
              key: 'recent',
              label: (
                <span>
                  <HistoryOutlined /> 最近使用 ({recentData?.items?.length || 0})
                </span>
              ),
              children: (
                <div className="nfc-directory-secondary-list">
                  {!recentData?.items || recentData.items.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="暂无最近使用记录"
                    />
                  ) : (
                    <List
                      size="small"
                      dataSource={recentData.items}
                      renderItem={(rec) => (
                        <List.Item className="nfc-directory-secondary-item">
                          actions={[
                            <Button
                              key="jump"
                              size="small"
                              type="link"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleNavigate(rec.path);
                              }}
                            >
                              进入目录
                            </Button>,
                            multiple ? (
                              <div
                                key="chk"
                                onClick={(e) => e.stopPropagation()}
                                className="nfc-directory-item-checkbox"
                              >
                                <Checkbox
                                  checked={selectedPaths.includes(rec.path)}
                                  onClick={(e) => e.stopPropagation()}
                                  onChange={() => handleToggleSelect(rec.path)}
                                />
                              </div>
                            ) : (
                              <Button
                                key="sel"
                                size="small"
                                type={selectedPaths.includes(rec.path) ? 'primary' : 'default'}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedPaths([rec.path]);
                                }}
                              >
                                {selectedPaths.includes(rec.path) ? '已选' : '选择'}
                              </Button>
                            ),
                          ]}
                          onClick={() => handleNavigate(rec.path)}
                        >
                          <List.Item.Meta
                            avatar={
                              <HistoryOutlined className="nfc-directory-recent-icon" />
                            }
                            title={<Text strong>{rec.path}</Text>}
                            description={
                              <Text type="secondary" className="nfc-directory-item-path">
                                最近使用时间：{formatDateTime(rec.last_used_at)}
                              </Text>
                            }
                          />
                        </List.Item>
                      )}
                    />
                  )}
                </div>
              ),
            },
          ]}
        />
      </div>
    </Modal>
  );
};
