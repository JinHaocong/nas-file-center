import React from 'react';
import { Breadcrumb, Button, Dropdown, MenuProps } from 'antd';
import { HomeOutlined, FolderOutlined, DownOutlined } from '@ant-design/icons';

interface PathBreadcrumbProps {
  currentPath: string;
  allowedRoots?: string[];
  onNavigate: (path: string) => void;
}

export const PathBreadcrumb: React.FC<PathBreadcrumbProps> = ({
  currentPath,
  allowedRoots = [],
  onNavigate,
}) => {
  if (!currentPath) {
    return null;
  }

  const cleanCurrent = currentPath.replace(/\/+$/, '');

  // Find the most specific matching allowedRoot for currentPath
  const matchingRoots = allowedRoots
    .filter((r) => cleanCurrent === r.replace(/\/+$/, '') || cleanCurrent.startsWith(r.replace(/\/+$/, '') + '/'))
    .sort((a, b) => b.length - a.length);

  const baseRoot = matchingRoots[0] || (allowedRoots.length > 0 ? allowedRoots[0].replace(/\/+$/, '') : cleanCurrent);

  // Build root switcher or root button
  const rootMenuItems: MenuProps['items'] = allowedRoots.map((root) => ({
    key: root,
    label: root,
    icon: <FolderOutlined />,
    onClick: () => onNavigate(root),
  }));

  const rootButton = allowedRoots.length > 1 ? (
    <Dropdown menu={{ items: rootMenuItems }} trigger={['click']}>
      <Button
        type="link"
        size="small"
        icon={<HomeOutlined />}
        style={{ padding: '0 4px', fontWeight: 600 }}
      >
        {baseRoot} <DownOutlined style={{ fontSize: 10 }} />
      </Button>
    </Dropdown>
  ) : (
    <Button
      type="link"
      size="small"
      icon={<HomeOutlined />}
      style={{ padding: '0 4px', fontWeight: 600 }}
      onClick={() => onNavigate(baseRoot)}
    >
      {baseRoot}
    </Button>
  );

  const items = [
    {
      title: rootButton,
    },
  ];

  // Derive sub-segments relative to baseRoot
  const cleanBaseRoot = baseRoot.replace(/\/+$/, '');
  let relPath = '';
  if (cleanCurrent === cleanBaseRoot) {
    relPath = '';
  } else if (cleanCurrent.startsWith(cleanBaseRoot + '/')) {
    relPath = cleanCurrent.slice(cleanBaseRoot.length).replace(/^\/+/, '');
  }

  if (relPath) {
    const segments = relPath.split('/').filter(Boolean);
    segments.forEach((seg, idx) => {
      const isLast = idx === segments.length - 1;
      const target = `${cleanBaseRoot}/${segments.slice(0, idx + 1).join('/')}`;

      items.push({
        title: isLast ? (
          <span style={{ fontWeight: 600, color: 'inherit', padding: '0 4px' }}>
            <FolderOutlined style={{ marginRight: 4 }} />
            {seg}
          </span>
        ) : (
          <Button
            type="link"
            size="small"
            style={{ padding: '0 4px' }}
            onClick={() => onNavigate(target)}
          >
            {seg}
          </Button>
        ),
      });
    });
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 4 }}>
      <Breadcrumb items={items} />
    </div>
  );
};
