import localFont from 'next/font/local';

export const circular = localFont({
  src: [
    { path: './Circular/CircularStd-Book.otf', weight: '400', style: 'normal' },
    { path: './Circular/CircularStd-Medium.otf', weight: '500', style: 'normal' },
    { path: './Circular/CircularStd-Bold.otf', weight: '700', style: 'normal' },
    { path: './Circular/CircularStd-Black.otf', weight: '900', style: 'normal' },
  ],
  variable: '--font-circular',
  display: 'swap',
});