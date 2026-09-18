import React from 'react';
import { useResponsive } from '../../hooks/useResponsive';

interface ResponsiveDataViewProps {
  desktop: React.ReactNode;
  mobile: React.ReactNode;
  className?: string;
}

export const ResponsiveDataView: React.FC<ResponsiveDataViewProps> = ({
  desktop,
  mobile,
  className = '',
}) => {
  const { isMobile } = useResponsive();

  return (
    <div className={`nfc-responsive-data-view ${isMobile ? 'nfc-responsive-data-mobile' : 'nfc-responsive-data-desktop'} ${className}`.trim()}>
      {isMobile ? mobile : desktop}
    </div>
  );
};
