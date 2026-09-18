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
        className="nfc-path-breadcrumb-root"
      >
        {baseRoot} <DownOutlined className="nfc-path-breadcrumb-chevron" />
      </Button>
    </Dropdown>
  ) : (
    <Button
      type="link"
      size="small"
      icon={<HomeOutlined />}
      className="nfc-path-breadcrumb-root"
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
          <span className="nfc-path-breadcrumb-current">
            <FolderOutlined className="nfc-path-breadcrumb-folder" />
            {seg}
          </span>
        ) : (
          <Button
            type="link"
            size="small"
            className="nfc-path-breadcrumb-link"
            onClick={() => onNavigate(target)}
          >
            {seg}
          </Button>
        ),
      });
    });
  }

  return (
    <div className="nfc-path-breadcrumb">
      <Breadcrumb items={items} />
    </div>
  );
};
