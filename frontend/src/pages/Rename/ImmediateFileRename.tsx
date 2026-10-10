import React from 'react';
import { ImmediateRenameEditor } from './ImmediateRenameEditor';

/** First-level regular files only; preserve_extension defaults to true. */
export const ImmediateFileRename: React.FC = () => <ImmediateRenameEditor kind="file" />;
