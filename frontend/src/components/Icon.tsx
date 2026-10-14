import type { SVGProps } from 'react'

const P: Record<string, string> = {
  moon: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z',
  library: 'M4 5v14M9 5v14M14 6l4 13M4 19h16',
  route: 'M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM8 17h6a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h6',
  heart: 'M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.600-7 10-7 10Z',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19 12l2-1.200-1.500-2.600-2.300.6a7 7 0 0 0-1.800-1L14.800 5h-3l-.6 2.800a7 7 0 0 0-1.800 1l-2.300-.6L5.600 10.800 7.600 12l-2 1.200 1.500 2.600 2.300-.6a7 7 0 0 0 1.800 1l.6 2.800h3l.6-2.800a7 7 0 0 0 1.800-1l2.300.6 1.500-2.600Z',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM20 20l-4-4',
  undo: 'M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',
  cut: 'M6 6l12 12M6 18 18 6',
  bookmark: 'M7 4h10v16l-5-4-5 4Z',
  check: 'm5 12 5 5L19 7',
  play: 'M8 5v14l11-7Z',
  warn: 'M12 4 3 19h18L12 4ZM12 10v4M12 17v.5',
  star: 'm12 3.500 2.600 5.400 5.900.8-4.300 4.100 1 5.800L12 16.800 6.800 19.600l1-5.800L3.500 9.700l5.900-.8Z',
  close: 'M6 6l12 12M18 6 6 18',
  chevron: 'm9 6 6 6-6 6',
  down: 'm6 9 6 6 6-6',
  upload: 'M12 16V4M7 9l5-5 5 5M5 20h14',
  download: 'M12 4v12M7 11l5 5 5-5M5 20h14',
  refresh: 'M20 11a8 8 0 0 0-14-4M4 4v4h4M4 13a8 8 0 0 0 14 4M20 20v-4h-4',
  link: 'M10 14a4 4 0 0 0 5.700 0l3-3a4 4 0 0 0-5.700-5.700L12 6.300M14 10a4 4 0 0 0-5.700 0l-3 3a4 4 0 0 0 5.700 5.700L12 17.700',
  sliders: 'M4 7h9M17 7h3M4 17h3M11 17h9M15 4v6M9 14v6',
  clap: 'M4 10h16v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1ZM4 10l-.8-3.600a1 1 0 0 1 .7-1.200L18 1.500l1.200 4.400M8 4l2.500 3.500M13 2.800 15.500 6.300',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12ZM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13',
  plus: 'M12 5v14M5 12h14',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3 2',
  film: 'M4 4h16v16H4ZM8 4v16M16 4v16M4 9h4M4 15h4M16 9h4M16 15h4',
  bolt: 'M13 3 5 14h6l-1 7 8-11h-6Z',
  sparkle: 'M12 3l1.800 5.200L19 10l-5.200 1.800L12 17l-1.800-5.200L5 10l5.200-1.800ZM19 17l.7 1.800L21.500 19.500l-1.800.7L19 22l-.7-1.800-1.800-.7 1.800-.7Z',
  tv: 'M4 7h16v11H4ZM9 21h6M8 3l4 4 4-4',
  download2: 'M12 3v12m0 0-4-4m4 4 4-4M5 21h14',
}

export type IconName = keyof typeof P

export function Icon({ name, size = 20, ...rest }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      <path d={P[name]} />
    </svg>
  )
}
