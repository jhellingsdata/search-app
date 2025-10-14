import './globals.css'
import { circular } from './fonts/circular'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Eco Search',
  description: 'Search for articles about the environment',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={circular.variable}>
      <body>
        {children}
      </body>
    </html>
  )
}
