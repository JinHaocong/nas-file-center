import { Grid } from 'antd';

const { useBreakpoint } = Grid;

export interface ResponsiveState {
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
}

export const useResponsive = (): ResponsiveState => {
  const screens = useBreakpoint();

  const isMobile = !screens.md;
  const isDesktop = Boolean(screens.xl);
  const isTablet = !isMobile && !isDesktop;

  return {
    isMobile,
    isTablet,
    isDesktop,
  };
};
