interface Props {
  size?: number;
  style?: React.CSSProperties;
}

// S-shape neural logo: two arc bowls + horizontal caps + crossover
// Mirrors the public/icon-*.png design
export default function AxonLogo({ size = 48, style }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 512 512"
      xmlns="http://www.w3.org/2000/svg"
      style={style}
    >
      <defs>
        <radialGradient id="axbg" cx="40%" cy="35%" r="70%">
          <stop offset="0%" stopColor="#3a2f0a" />
          <stop offset="100%" stopColor="#0d0a02" />
        </radialGradient>
        <filter id="axglow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="14" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <filter id="axnode" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="18" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {/* Background */}
      <rect x="0" y="0" width="512" height="512" rx="128" ry="128" fill="url(#axbg)" />

      {/* S strokes — glow layer */}
      <g filter="url(#axglow)" stroke="#D4AF37" strokeWidth="52" fill="none" strokeLinecap="round" opacity="0.55">
        {/* top cap */}
        <line x1="165" y1="85" x2="347" y2="85" />
        {/* upper arc (left side, ⊂ bowl) — 60° CW arc from (165,85) through left to (165,255) */}
        <path d="M347,85 A170,170 0 0,0 347,255" />
        {/* crossover */}
        <line x1="347" y1="255" x2="165" y2="257" />
        {/* lower arc (right side, ⊃ bowl) — 60° CW arc */}
        <path d="M165,257 A170,170 0 0,0 165,427" />
        {/* bottom cap */}
        <line x1="165" y1="427" x2="347" y2="427" />
      </g>

      {/* S strokes — crisp layer */}
      <g stroke="#FFD700" strokeWidth="18" fill="none" strokeLinecap="round" opacity="0.9">
        <line x1="165" y1="85" x2="347" y2="85" />
        <path d="M347,85 A170,170 0 0,0 347,255" />
        <line x1="347" y1="255" x2="165" y2="257" />
        <path d="M165,257 A170,170 0 0,0 165,427" />
        <line x1="165" y1="427" x2="347" y2="427" />
      </g>

      {/* Nodes */}
      {([
        [165, 85],
        [347, 85],
        [347, 255],
        [165, 257],
        [165, 427],
        [347, 427],
      ] as [number, number][]).map(([cx, cy], i) => (
        <g key={i}>
          <circle cx={cx} cy={cy} r="36" fill="#FFD700" opacity="0.35" filter="url(#axnode)" />
          <circle cx={cx} cy={cy} r="24" fill="#FFE066" opacity="0.9" />
          <circle cx={cx} cy={cy} r="12" fill="#FFFBEB" />
        </g>
      ))}
    </svg>
  );
}
