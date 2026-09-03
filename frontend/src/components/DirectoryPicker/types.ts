export interface DirectoryPickerProps {
  value?: string | string[];
  onChange?: (value: any) => void;
  multiple?: boolean;
  disabled?: boolean;
  placeholder?: string;
  allowManualInput?: boolean;
}

export interface DirectoryPickerModalProps {
  open: boolean;
  onCancel: () => void;
  onConfirm: (selected: string | string[]) => void;
  multiple?: boolean;
  initialPath?: string;
  selectedValues?: string | string[];
}
