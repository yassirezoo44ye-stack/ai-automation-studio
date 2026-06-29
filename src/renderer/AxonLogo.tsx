interface Props {
  size?: number;
  style?: React.CSSProperties;
}

export default function AxonLogo({ size = 48, style }: Props) {
  const r = size / 4;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      xmlns="http://www.w3.org/2000/svg"
      style={style}
    >
      <defs>
        <radialGradient id="bg" cx="40%" cy="35%" r="70%">
          <stop offset="0%" stopColor="#2d1060" />
          <stop offset="100%" stopColor="#0a0518" />
        </radialGradient>
        <filter id="glow">
          <feGaussianBlur stdDeviation="2.5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <filter id="nodeGlow">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {/* Background */}
      <rect x="0" y="0" width="100" height="100" rx="24" ry="24" fill="url(#bg)" />

      {/* Glow lines */}
      <g filter="url(#glow)" opacity="0.6">
        <line x1="50" y1="14" x2="14" y2="86" stroke="#8b5cf6" strokeWidth="7" strokeLinecap="round" />
        <line x1="50" y1="14" x2="86" y2="86" stroke="#8b5cf6" strokeWidth="7" strokeLinecap="round" />
        <line x1="30" y1="53" x2="70" y2="53" stroke="#8b5cf6" strokeWidth="7" strokeLinecap="round" />
      </g>

      {/* Crisp lines */}
      <g opacity="0.9">
        <line x1="50" y1="14" x2="14" y2="86" stroke="#a78bfa" strokeWidth="3.5" strokeLinecap="round" />
        <line x1="50" y1="14" x2="86" y2="86" stroke="#a78bfa" strokeWidth="3.5" strokeLinecap="round" />
        <line x1="30" y1="53" x2="70" y2="53" stroke="#a78bfa" strokeWidth="3.5" strokeLinecap="round" />
      </g>

      {/* Nodes */}
      {[
        [50, 14],
        [14, 86],
        [86, 86],
        [30, 53],
        [70, 53],
      ].map(([cx, cy], i) => (
        <g key={i} filter="url(#nodeGlow)">
          <circle cx={cx} cy={cy} r="6" fill="#c4b5fd" opacity="0.9" />
          <circle cx={cx} cy={cy} r="3" fill="#f5f3ff" />
        </g>
      ))}
    </svg>
  );
}
