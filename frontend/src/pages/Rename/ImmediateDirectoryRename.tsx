import React from 'react';
import { ImmediateRenameEditor } from './ImmediateRenameEditor';

/** First-level directories only; no direct filesystem action is exposed. */
export const ImmediateDirectoryRename: React.FC = () => <ImmediateRenameEditor kind="directory" />;
