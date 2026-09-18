import React from 'react';
import { Typography } from 'antd';

const { Text } = Typography;

interface CodePathProps {
  value?: string | null;
  muted?: boolean;
}

export const CodePath: React.FC<CodePathProps> = ({ value, muted = false }) => {
  if (!value) {
    return <span className="nfc-code-path nfc-code-path-empty">—</span>;
  }

  return (
    <Text
      code
      copyable={{ text: value }}
      ellipsis={{ tooltip: value }}
      className={`nfc-code-path ${muted ? 'nfc-code-path-muted' : ''}`.trim()}
    >
      {value}
    </Text>
  );
};
